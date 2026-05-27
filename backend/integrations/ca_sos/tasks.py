"""
California SOS Celery tasks.

Stage 1 — sync_ca_elections:
  Seed Election records for the current even-year CA election cycle using
  statutory dates. Fetch and fingerprint the CA SOS endpoint catalog CSV
  from media.sos.ca.gov. If the catalog has changed, queue sync_ca_races.

Stage 2 — sync_ca_races:
  For each contest in the endpoint catalog, call the CA SOS REST API
  (/returns/{contest}) to get race + candidate data.
  Upsert Race + Candidate records.
  Candidates absent from this run are marked WITHDRAWN.
"""
import json
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import CaSosClient
from .exceptions import CaSosError, CaSosRetryableError
from .mappers import build_election_source_id, map_candidate, map_election, map_race
from .parsers import deduplicate_catalog, parse_endpoint_catalog

logger = logging.getLogger(__name__)

_CATALOG_CACHE_KEY = "ca_sos:endpoint_catalog_fingerprint"
_CATALOG_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days
_ELECTION_TYPES = ("primary", "general")


def _current_even_year() -> int:
    from django.utils import timezone as tz
    year = tz.localdate().year
    return year if year % 2 == 0 else year + 1


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ca_elections(self):
    """
    Stage 1: Seed CA Election records and queue Stage 2 if the endpoint
    catalog has changed.
    """
    sync_log = SyncLog.objects.create(
        source="ca_sos",
        task_name="sync_ca_elections",
        status=SyncLog.Status.STARTED,
    )
    client = CaSosClient()
    created_count = updated_count = 0

    try:
        year = _current_even_year()

        for election_type in _ELECTION_TYPES:
            mapped = map_election(year, election_type)
            source_id = mapped.pop("source_id")
            _, created = Election.objects.update_or_create(
                source_id=source_id,
                defaults={**mapped, "last_synced_at": timezone.now()},
            )
            created_count += int(created)
            updated_count += int(not created)

        logger.info(
            "ca_sos.sync_elections.seeded year=%d created=%d updated=%d",
            year, created_count, updated_count,
        )

        # Check if endpoint catalog has changed
        fingerprint = client.get_endpoint_catalog_fingerprint()
        if fingerprint is None:
            logger.warning("ca_sos.sync_elections.catalog_unavailable year=%d", year)
            sync_log.notes = "Endpoint catalog unavailable; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "updated": updated_count, "queued": 0}

        last_fingerprint = cache.get(_CATALOG_CACHE_KEY)
        if fingerprint == last_fingerprint:
            logger.info("ca_sos.sync_elections.catalog_unchanged year=%d", year)
            sync_log.records_created = created_count
            sync_log.records_updated = updated_count
            sync_log.notes = "Catalog unchanged; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=[
                "records_created", "records_updated", "notes", "status", "completed_at",
            ])
            return {"created": created_count, "updated": updated_count, "queued": 0}

        # Catalog changed — fetch full CSV and queue Stage 2
        logger.info(
            "ca_sos.sync_elections.catalog_updated fingerprint=%s year=%d",
            fingerprint, year,
        )
        csv_bytes = client.fetch_endpoint_catalog_csv()
        entries = deduplicate_catalog(parse_endpoint_catalog(csv_bytes))

        if not entries:
            logger.warning(
                "ca_sos.sync_elections.empty_catalog year=%d fingerprint=%s",
                year, fingerprint,
            )
            sync_log.notes = "Catalog parsed but no usable endpoints found"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "updated": updated_count, "queued": 0}

        # Determine which election to associate races with (prefer active, then upcoming)
        election_obj = _resolve_current_election(year)
        if election_obj is None:
            logger.warning(
                "ca_sos.sync_elections.no_current_election year=%d", year
            )
            sync_log.notes = "No current CA election found; races not synced"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "updated": updated_count, "queued": 0}

        catalog_json = json.dumps(entries)
        sync_ca_races.delay(election_obj.pk, catalog_json, fingerprint)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"Queued sync_ca_races: {len(entries)} contests"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "queued": 1}

    except CaSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("ca_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


def _resolve_current_election(year: int) -> Election | None:
    """
    Return the most-relevant CA election for the given year.
    Preference: ACTIVE > RESULTS_PENDING (most recent) > UPCOMING (earliest).
    """
    qs = Election.objects.filter(
        state="CA",
        source_id__startswith=f"ca_sos_{year}_",
    )
    active = qs.filter(status=Election.Status.ACTIVE).first()
    if active:
        return active

    pending = qs.filter(status=Election.Status.RESULTS_PENDING).order_by("-election_date").first()
    if pending:
        return pending

    return qs.filter(status=Election.Status.UPCOMING).order_by("election_date").first()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ca_races(self, election_pk: int, catalog_json: str, fingerprint: str):
    """
    Stage 2: Parse the CA SOS endpoint catalog and upsert Race + Candidate
    records by calling each contest endpoint.

    After successful sync, stores the catalog fingerprint in Redis so future
    Stage 1 runs skip unchanged catalogs.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("ca_sos.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="ca_sos",
        task_name="sync_ca_races",
        status=SyncLog.Status.STARTED,
    )
    client = CaSosClient()
    created_count = updated_count = withdrawn_count = error_count = 0
    seen_candidate_pks: set[int] = set()

    try:
        entries = json.loads(catalog_json)

        for entry in entries:
            endpoint_path = entry["path"]
            try:
                contests = client.fetch_contest(endpoint_path)
            except CaSosError as exc:
                logger.warning(
                    "ca_sos.sync_races.contest_error endpoint=%s err=%s",
                    endpoint_path, exc,
                )
                error_count += 1
                continue

            if not contests:
                continue

            for contest in contests:
                race_defaults = map_race(election_obj, {
                    **entry,
                    # Prefer raceTitle from API response if available
                    "name": contest.get("raceTitle") or entry["name"],
                })
                canonical_key = race_defaults.pop("canonical_key")

                race, race_created = Race.objects.update_or_create(
                    canonical_key=canonical_key,
                    defaults={
                        "election": election_obj,
                        **race_defaults,
                        "last_synced_at": timezone.now(),
                    },
                )
                created_count += int(race_created)
                updated_count += int(not race_created)

                raw_candidates = contest.get("candidates") or []
                for raw_cand in raw_candidates:
                    name = (raw_cand.get("Name") or "").strip()
                    if not name:
                        continue
                    cand_obj, cand_created = Candidate.objects.update_or_create(
                        race=race,
                        name=name,
                        defaults=map_candidate(raw_cand),
                    )
                    seen_candidate_pks.add(cand_obj.pk)
                    created_count += int(cand_created)
                    updated_count += int(not cand_created)

        # Mark candidates absent from this run as WITHDRAWN
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj, race__source=Race.Source.CA_SOS)
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(
            candidate_status=Candidate.CandidateStatus.WITHDRAWN
        )
        if withdrawn_count:
            logger.info(
                "ca_sos.sync_races.withdrawn election=%s count=%d",
                election_obj.source_id, withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        # Store fingerprint so Stage 1 skips unchanged catalogs
        cache.set(_CATALOG_CACHE_KEY, fingerprint, _CATALOG_CACHE_TTL)

        status = SyncLog.Status.COMPLETED if not error_count else SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.error_count = error_count
        sync_log.notes = f"withdrawn={withdrawn_count} errors={error_count}"
        sync_log.status = status
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "error_count",
            "notes", "status", "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "withdrawn": withdrawn_count,
            "errors": error_count,
        }

    except CaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ca_sos.sync_races.failed election=%s", election_obj.source_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
