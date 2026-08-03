from __future__ import annotations

import dataclasses
import datetime
import logging
import re

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from results.adapters import list_supported_states
from results.adapters.registry import get_adapter

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=12, default_retry_delay=3600)
def ingest_official_results(self, state: str, election_id: int):
    """
    Fetch and upsert official results for all races in the given election.
    Retries hourly; gives up after 12 attempts (12 hours post-trigger).

    When no races exist for the election, auto-bootstraps Race/Candidate/
    MeasureOption rows from the result data before processing results.
    """
    from elections.models import Election, Race

    adapter_class = get_adapter(state)
    if not adapter_class:
        logger.warning("ingest_official_results: no adapter for state %s; skipping", state)
        return

    try:
        election = Election.objects.get(pk=election_id)
    except Election.DoesNotExist:
        logger.error("ingest_official_results: election %s not found", election_id)
        return

    adapter = adapter_class()

    # If no races exist, clear any stale version cache so the adapter performs
    # a full fetch.  A prior run may have cached the version while races were
    # still empty (loop body never executed), causing all future calls to
    # short-circuit on unchanged=True without ever bootstrapping.
    if not Race.objects.filter(election=election).exists():
        if hasattr(adapter, 'version_cache_key'):
            stale_key = adapter.version_cache_key(election_id)
            if cache.get(stale_key):
                logger.info(
                    "ingest_official_results: clearing stale version cache for election %s (%s) — no races exist",
                    election_id, state,
                )
                cache.delete(stale_key)

    try:
        result = adapter.fetch_results(election.election_date, election_id)
    except Exception as exc:
        logger.exception("ingest_official_results: adapter fetch failed for %s/%s", state, election_id)
        raise self.retry(exc=exc)

    if result.unchanged:
        logger.info(
            "ingest_official_results: version unchanged for election %s (%s); skipping",
            election_id, state,
        )
        return

    if not result.rows:
        # 'none' confidence means the adapter never attempted a fetch (e.g. no
        # results_url configured yet) — nothing was found to be "partial", so
        # leave races pending rather than mislabeling them as partial_results
        # with zero rows in results_officialresult. Only a genuine partial
        # mapping ('partial') earns that status.
        certification_status = (
            Race.CertificationStatus.PARTIAL_RESULTS
            if result.mapping_confidence == 'partial'
            else Race.CertificationStatus.RESULTS_PENDING
        )
        Race.objects.filter(election=election).update(certification_status=certification_status)
        return

    races = list(Race.objects.filter(election=election).select_related('election'))
    if not races:
        races = _bootstrap_races_from_results(election, result, state)

    for race in races:
        _process_race_results(race, result, state)

    # Adapters with their own (finer-grained, e.g. per-endpoint) version cache
    # stage pending writes during fetch_results() and expose commit_versions()
    # to flush them — called here so a version is only marked processed once
    # the corresponding rows have actually been persisted above. If the loop
    # above raises, this line is never reached and nothing gets staged as
    # cached, so the next run re-fetches and re-persists it.
    if hasattr(adapter, 'commit_versions'):
        adapter.commit_versions()

    # Write version to cache only after successful DB work AND races were processed.
    # Gating on `races` prevents caching a version that corresponds to an empty-race state.
    if (
        races
        and result.mapping_confidence == 'full'
        and result.source_version
        and hasattr(adapter, 'version_cache_key')
    ):
        cache.set(
            adapter.version_cache_key(election_id),
            result.source_version,
            timeout=adapter.VERSION_CACHE_TIMEOUT,
        )


# Keywords that indicate a ballot measure race when found in the office_title.
_MEASURE_TITLE_KEYWORDS = frozenset({
    'amendment', 'measure', 'proposition', 'prop', 'question',
    'referendum', 'initiative', 'bond', 'levy', 'renewal',
    'ordinance', 'resolution',
})


def _is_measure_race(office_title: str) -> bool:
    """Return True when office_title keywords indicate a ballot measure."""
    normalized = office_title.strip().lower()
    return any(kw in normalized for kw in _MEASURE_TITLE_KEYWORDS)


def _row_source_identity(row) -> dict[str, str]:
    raw = row.raw or {}
    contest_code = str(raw.get("contest_code") or "").strip()
    if not contest_code:
        return {}

    identity = {}
    for key in ("contest_code", "party_code"):
        value = str(raw.get(key) or "").strip()
        if value:
            identity[key] = value
    return identity


def _race_source_identity(race) -> dict[str, str]:
    metadata = race.source_metadata or {}
    identity = {}
    for key in ("contest_code", "party_code"):
        value = str(metadata.get(key) or "").strip()
        if value:
            identity[key] = value
    return identity


def _office_title_key(office_title: str) -> str:
    return " ".join((office_title or "").strip().lower().split())


# Clarity represents a partisan primary as one contest per party, with the
# party appended to the office title ("Governor - DEM", "U.S. Senate - REP").
# Some states (e.g. SC) pre-create a single consolidated, non-partisan Race
# per office spanning candidates from every party — so the exact office_title
# match fails for every row even though the candidates match fine downstream.
# Stripping this suffix is only tried as a fallback, after an exact match.
_PARTY_SUFFIX_RE = re.compile(r'\s*-\s*(dem|rep|gop|ind|una|con|lib|grn)$')


def _office_title_key_base(office_title: str) -> str:
    return _PARTY_SUFFIX_RE.sub('', _office_title_key(office_title))


# A source's candidate/race metadata feed and its results feed can format the
# same office differently even after stripping party — e.g. SC's sc_vrems
# reports "City Council at Large, Florence" while the Clarity contest name for
# the same race is "City Council at Large Florence" (no comma). Stripping
# punctuation is only tried as a last-resort fallback, after exact and
# party-suffix matches, since it loosens the comparison the most.
_PUNCT_RE = re.compile(r'[.,]')


def _office_title_key_loose(office_title: str) -> str:
    return _PUNCT_RE.sub('', _office_title_key_base(office_title))


def _bootstrap_races_from_results(election, adapter_result, state: str) -> list:
    """
    Auto-create Race, Candidate, and MeasureOption rows from result data when
    none exist for the election.  Runs inside a serialised transaction so that
    concurrent Celery workers cannot create duplicate races.

    Returns the list of races available for processing (newly created, or
    those created by a concurrent worker that won the lock).
    """
    from elections.models import Candidate, Election, MeasureOption, Race

    rows_by_race: dict[tuple[str, tuple[tuple[str, str], ...]], list] = {}
    title_by_key: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}
    for row in adapter_result.rows:
        title = (row.office_title or '').strip()
        if not title:
            continue
        identity = tuple(sorted(_row_source_identity(row).items()))
        key = (title, identity)
        rows_by_race.setdefault(key, []).append(row)
        title_by_key[key] = title

    if not rows_by_race:
        logger.warning(
            "_bootstrap_races_from_results: no office_titles in result rows for election %s; cannot bootstrap",
            election.pk,
        )
        return []

    with transaction.atomic():
        # Lock the election row to serialise concurrent bootstrap attempts.
        Election.objects.select_for_update().filter(pk=election.pk).get()

        existing = list(Race.objects.filter(election=election).select_related('election'))
        if existing:
            # Another worker already bootstrapped while we waited for the lock.
            logger.info(
                "_bootstrap_races_from_results: races already exist for election %s; skipping bootstrap",
                election.pk,
            )
            return existing

        created_races = []
        for key, rows in rows_by_race.items():
            office_title = title_by_key[key]
            identity = dict(key[1])
            race_type = (
                Race.RaceType.MEASURE if _is_measure_race(office_title)
                else Race.RaceType.CANDIDATE
            )
            race = Race.objects.create(
                election=election,
                race_type=race_type,
                office_title=office_title,
                jurisdiction=election.state or '',
                geography_scope='statewide',
                certification_status=Race.CertificationStatus.RESULTS_PENDING,
                source=Race.Source.RESULTS_ADAPTER,
                race_status=Race.RaceStatus.ACTIVE,
                match_confidence=Race.MatchConfidence.LOW,
                source_metadata={
                    'bootstrapped_from': 'results_adapter',
                    'state': state,
                    **identity,
                },
            )
            created_races.append(race)
            logger.info(
                "_bootstrap_races_from_results: created %s race %s ('%s') for election %s",
                race_type, race.pk, office_title, election.pk,
            )

            if race_type == Race.RaceType.CANDIDATE:
                names_seen: set[str] = set()
                for row in rows:
                    name = (row.candidate_name or '').strip()
                    if not name or name in names_seen:
                        continue
                    names_seen.add(name)
                    Candidate.objects.create(
                        race=race,
                        name=name,
                        candidate_status=(
                            Candidate.CandidateStatus.WRITE_IN
                            if row.is_write_in_aggregate
                            else Candidate.CandidateStatus.RUNNING
                        ),
                    )
            else:
                labels_seen: set[str] = set()
                for row in rows:
                    # Clarity sets candidate_name for measure choices; fall back to it.
                    label = (row.option_label or row.candidate_name or '').strip()
                    if not label or label in labels_seen:
                        continue
                    labels_seen.add(label)
                    MeasureOption.objects.create(race=race, option_label=label)

    logger.info(
        "_bootstrap_races_from_results: bootstrapped %d races for election %s (%s)",
        len(created_races), election.pk, state,
    )
    return created_races


def _process_race_results(race, adapter_result, state: str):
    from elections.models import Candidate, MeasureOption, Race
    from results.models import OfficialResult

    # --- Filter rows to this race by source identity or office_title ---------
    race_identity = _race_source_identity(race)
    if race_identity:
        filtered_rows = [
            r for r in adapter_result.rows
            if all(_row_source_identity(r).get(key) == value for key, value in race_identity.items())
        ]
        if not filtered_rows:
            logger.debug(
                "_process_race_results: no source identity match for race %s ('%s') in %s",
                race.id, race.office_title, state,
            )
            race.certification_status = Race.CertificationStatus.PARTIAL_RESULTS
            race.save(update_fields=['certification_status'])
            return
    else:
        filtered_rows = None

    has_office_titles = any(r.office_title for r in adapter_result.rows)
    if filtered_rows is None and has_office_titles:
        race_key = _office_title_key(race.office_title)
        filtered_rows = [
            r for r in adapter_result.rows
            if r.office_title and _office_title_key(r.office_title) == race_key
        ]
        if not filtered_rows:
            # Fall back to matching per-party primary contests ("Governor - DEM"
            # and "Governor - REP") against a single consolidated Race.
            filtered_rows = [
                r for r in adapter_result.rows
                if r.office_title and _office_title_key_base(r.office_title) == race_key
            ]
        if not filtered_rows:
            # Last resort: ignore punctuation differences between the race's
            # source (e.g. "City Council at Large, Florence") and the results
            # feed's contest name (e.g. "City Council at Large Florence - DEM").
            race_key_loose = _office_title_key_loose(race.office_title)
            filtered_rows = [
                r for r in adapter_result.rows
                if r.office_title and _office_title_key_loose(r.office_title) == race_key_loose
            ]
        if not filtered_rows:
            # Feed has office titles but none matched this race — skip rather than
            # risk corrupting it with results from a different contest.
            logger.debug(
                "_process_race_results: no office_title match for race %s ('%s') in %s",
                race.id, race.office_title, state,
            )
            race.certification_status = Race.CertificationStatus.PARTIAL_RESULTS
            race.save(update_fields=['certification_status'])
            return
    elif filtered_rows is None:
        filtered_rows = list(adapter_result.rows)

    # --- Coerce candidate_name → option_label for measure races ---------------
    # Clarity uses CH[] for both candidate and ballot measure choices.
    # When the matched race is a MEASURE, treat candidate_name as option_label.
    if race.race_type == Race.RaceType.MEASURE:
        coerced = []
        for row in filtered_rows:
            if row.candidate_name is not None and row.option_label is None:
                row = dataclasses.replace(row, option_label=row.candidate_name, candidate_name=None)
            coerced.append(row)
        filtered_rows = coerced

    # --- Match each row to a Candidate or MeasureOption ----------------------
    matched_rows = []
    any_partial = False

    for row in filtered_rows:
        candidate = None
        measure_option = None

        if row.is_write_in_aggregate:
            if race.race_type != Race.RaceType.CANDIDATE:
                continue
        elif row.candidate_name:
            if race.race_type != Race.RaceType.CANDIDATE:
                continue
            candidate = (
                Candidate.objects.filter(race=race, name=row.candidate_name).first()
                or Candidate.objects.filter(race=race, name__iexact=row.candidate_name).first()
            )
            if not candidate:
                logger.warning(
                    "_process_race_results: no candidate match for '%s' in race %s (%s)",
                    row.candidate_name, race.id, state,
                )
                any_partial = True
                continue
        elif row.option_label:
            if race.race_type != Race.RaceType.MEASURE:
                continue
            measure_option = (
                MeasureOption.objects.filter(race=race, option_label=row.option_label).first()
                or MeasureOption.objects.filter(race=race, option_label__iexact=row.option_label).first()
            )
            if not measure_option:
                logger.warning(
                    "_process_race_results: no measure option match for '%s' in race %s (%s)",
                    row.option_label, race.id, state,
                )
                any_partial = True
                continue
        else:
            any_partial = True
            continue

        with transaction.atomic():
            OfficialResult.objects.update_or_create(
                race=race,
                candidate=candidate,
                measure_option=measure_option,
                round_number=row.round_number,
                jurisdiction_fragment=row.jurisdiction_fragment,
                defaults={
                    'vote_count': row.vote_count,
                    'vote_pct': row.vote_pct,
                    'is_winner': row.is_winner,
                    'result_type': row.result_type,
                    'is_write_in_aggregate': row.is_write_in_aggregate,
                    'source_url': adapter_result.source_url,
                    'raw_payload': row.raw,
                    'certified_at': _certified_at_for_row(race, row.result_type),
                },
            )
        matched_rows.append(row)

    # --- Update race certification status ------------------------------------
    if adapter_result.mapping_confidence == 'full' and not any_partial and matched_rows:
        all_official = all(
            r.result_type == OfficialResult.ResultType.OFFICIAL for r in matched_rows
        )
        if all_official:
            race.certification_status = Race.CertificationStatus.RESULTS_CERTIFIED
            race.race_status = Race.RaceStatus.ARCHIVED
            race.save(update_fields=['certification_status', 'race_status'])
        else:
            # Full-confidence match but results are still unofficial (e.g. Clarity feed)
            race.certification_status = Race.CertificationStatus.RESULTS_PENDING
            race.save(update_fields=['certification_status'])
        return

    race.certification_status = Race.CertificationStatus.PARTIAL_RESULTS
    race.save(update_fields=['certification_status'])


def _certified_at_for_row(race, result_type: str):
    from results.models import OfficialResult

    if result_type != OfficialResult.ResultType.OFFICIAL:
        return None
    election_date = race.election.election_date
    if isinstance(election_date, str):
        election_date = datetime.date.fromisoformat(election_date)
    current_tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.datetime.combine(election_date, datetime.time.min), current_tz)


@shared_task(bind=True, max_retries=3)
def poll_pending_results(self):
    """
    Poll all past elections in RESULTS_PENDING status that have a supported adapter.
    Triggered daily via POST /internal/tasks/poll-results/ (Cloud Scheduler → ADR-002).
    """
    from elections.models import Election

    supported = set(list_supported_states())
    if not supported:
        logger.warning("poll_pending_results: no adapters registered; skipping")
        return {"queued": 0}

    elections = Election.objects.filter(
        election_date__lt=timezone.now().date(),
        status=Election.Status.RESULTS_PENDING,
        state__in=supported,
    )
    queued = 0
    for election in elections:
        ingest_official_results.delay(election.state, election.pk)
        logger.info(
            "poll_pending_results: queued ingest for election %s (%s, %s)",
            election.pk, election.state, election.election_date,
        )
        queued += 1

    logger.info("poll_pending_results: queued %d elections", queued)
    return {"queued": queued}
