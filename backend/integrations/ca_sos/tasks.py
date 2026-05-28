"""
California SOS Celery tasks.

Stage 1 — sync_ca_elections:
  Seed Election records for the current even-year CA election cycle using
  the catalog-derived date (when available) or statutory dates. Fetch and
  fingerprint the CA SOS endpoint catalog CSV from api.sos.ca.gov. If the
  catalog has changed, queue sync_ca_races.

Stage 2 — sync_ca_races:
  For each contest in the endpoint catalog, call the CA SOS REST API
  (/returns/{contest}) to get race + candidate data.
  Upsert Race + Candidate records via the aggregation ingest service.
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
    from aggregation import ingest

    from .mappers import map_election_identity
    from .parsers import (
        parse_api_endpoint_catalog,
        parse_election_date_from_catalog,
        parse_election_type_from_catalog,
    )

    sync_log = SyncLog.objects.create(
        source="ca_sos",
        task_name="sync_ca_elections",
        status=SyncLog.Status.STARTED,
    )
    client = CaSosClient()
    created_count = 0
    try:
        year = _current_even_year()

        fingerprint = client.get_endpoint_catalog_fingerprint()
        catalog_bytes = None
        catalog_date = None
        catalog_election_type = None
        if fingerprint is not None:
            catalog_bytes = client.fetch_endpoint_catalog_csv()
            catalog_date = parse_election_date_from_catalog(catalog_bytes)
            catalog_election_type = parse_election_type_from_catalog(catalog_bytes)

        elections = {}
        for election_type in _ELECTION_TYPES:
            # Apply the catalog-parsed date only to the election it actually
            # describes (primary vs general); otherwise fall back to the
            # statutory formula. Avoids stamping a November date onto a March
            # primary record when the general catalog is published.
            cdate = catalog_date if election_type == catalog_election_type else None
            identity, fields = map_election_identity(year, election_type, catalog_date=cdate)
            election, created = ingest.ingest_election(
                source="ca_sos",
                source_id=build_election_source_id(year, election_type),
                identity=identity,
                fields=fields,
            )
            elections[election_type] = election
            created_count += int(created)

        logger.info("ca_sos.sync_elections.seeded year=%d", year)

        if fingerprint is None:
            sync_log.notes = "Endpoint catalog unavailable; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        last_fingerprint = cache.get(_CATALOG_CACHE_KEY)
        if fingerprint == last_fingerprint:
            sync_log.notes = "Catalog unchanged; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        entries = deduplicate_catalog(parse_api_endpoint_catalog(catalog_bytes))
        if not entries:
            sync_log.notes = "Catalog parsed but no usable endpoints found"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": created_count, "queued": 0}

        # Route the races queue to the election the catalog describes; only
        # fall back if the title didn't match primary/general.
        election_obj = (
            elections.get(catalog_election_type)
            or elections.get("primary")
            or elections.get("general")
        )
        sync_ca_races.delay(election_obj.pk, json.dumps(entries), fingerprint)

        sync_log.notes = f"Queued sync_ca_races: {len(entries)} contests"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["notes", "status", "completed_at"])
        return {"created": created_count, "queued": 1}

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
    records by calling each contest endpoint via the aggregation ingest service.

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
        from aggregation import ingest

        from .mappers import infer_geography_scope, infer_race_type, normalize

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
                # source_metadata['ca_endpoint'] is required by the CA Stage-2
                # results adapter (backend/results/adapters/ca.py): it filters
                # races with source_metadata!={} and reads the endpoint from
                # there to drive results polling.
                race, _ = ingest.ingest_race(
                    election=election_obj,
                    source="ca_sos",
                    identity={
                        "office_title": contest.get("raceTitle") or entry["name"],
                        "ocd_division_id": "",
                        "race_type": infer_race_type(entry["type"]),
                    },
                    fields={
                        "office_title": contest.get("raceTitle") or entry["name"],
                        "jurisdiction": "California",
                        "geography_scope": infer_geography_scope(entry["name"]),
                        "results_url": f"https://api.sos.ca.gov{entry['path']}",
                        "certification_status": (
                            Race.CertificationStatus.RESULTS_PENDING
                            if election_obj.status == Election.Status.RESULTS_PENDING
                            else Race.CertificationStatus.UPCOMING
                        ),
                        "source_metadata": {
                            "ca_endpoint": entry["path"],
                            "ca_race_id": entry.get("race_id", ""),
                            "contest_type": entry["type"],
                        },
                    },
                )
                created_count += 1
                for raw_cand in (contest.get("candidates") or []):
                    cand_name = (raw_cand.get("Name") or "").strip()
                    if not cand_name:
                        continue
                    cand, _ = ingest.ingest_candidate(
                        race=race,
                        source="ca_sos",
                        name=cand_name,
                        party=(raw_cand.get("Party") or "").strip(),
                        fields={
                            "incumbent": bool(raw_cand.get("incumbent", False)),
                            "source_metadata": {
                                "ca_votes": raw_cand.get("Votes", ""),
                                "ca_percent": raw_cand.get("Percent", ""),
                            },
                        },
                    )
                    seen_candidate_pks.add(cand.pk)

        # Mark candidates absent from this run as WITHDRAWN
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj, race__source="ca_sos")
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
