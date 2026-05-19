from __future__ import annotations

import dataclasses
import datetime
import logging

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
        certification_status = (
            Race.CertificationStatus.PARTIAL_RESULTS
            if result.mapping_confidence in {'none', 'partial'}
            else Race.CertificationStatus.RESULTS_PENDING
        )
        Race.objects.filter(election=election).update(certification_status=certification_status)
        return

    races = Race.objects.filter(election=election).select_related('election')
    for race in races:
        _process_race_results(race, result, state)

    # Write version to cache only after all DB work succeeds (prevents skipping on retry).
    if result.source_version and hasattr(adapter, 'version_cache_key'):
        cache.set(
            adapter.version_cache_key(election_id),
            result.source_version,
            timeout=adapter.VERSION_CACHE_TIMEOUT,
        )


def _process_race_results(race, adapter_result, state: str):
    from elections.models import Candidate, MeasureOption, Race
    from results.models import OfficialResult

    # --- Filter rows to this race by office_title ----------------------------
    has_office_titles = any(r.office_title for r in adapter_result.rows)
    if has_office_titles:
        filtered_rows = [
            r for r in adapter_result.rows
            if r.office_title
            and ' '.join(r.office_title.strip().lower().split())
            == ' '.join(race.office_title.strip().lower().split())
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
    else:
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
