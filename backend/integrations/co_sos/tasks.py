"""
Colorado SOS Celery tasks.

Stage 1 — sync_co_elections:
  Seed Election records for upcoming Colorado elections using statutory dates.
  Check whether the candidate list HTML page has changed (via content hash).
  If so, queue sync_co_candidates.

Stage 2 — sync_co_candidates:
  Fetch + parse the candidate list HTML for one election type.
  Upsert Race + Candidate records.
  Mark candidates absent from this run as WITHDRAWN (catches removals after
  the page no longer shows a strikethrough for a dropped candidate).
"""
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import ColoradoSosClient
from .exceptions import CoSosRetryableError
from .mappers import (
    build_race_groups,
    map_candidate,
    map_election,
    map_race,
)
from .parsers import parse_candidate_table

logger = logging.getLogger(__name__)

_PAGE_CACHE_KEY = "co_sos:candidate_page_fingerprint:{election_type}"
_PAGE_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days

# Sync only primary for now; general petition page is incomplete
_ELECTION_TYPES = ("primary",)


def _current_even_year() -> int:
    from django.utils import timezone as tz
    year = tz.localdate().year
    return year if year % 2 == 0 else year + 1


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_co_elections(self):
    """
    Stage 1: Seed Colorado Election records via the aggregation ingest service
    and queue Stage 2 if the candidate list page has changed.
    """
    sync_log = SyncLog.objects.create(
        source="co_sos",
        task_name="sync_co_elections",
        status=SyncLog.Status.STARTED,
    )
    client = ColoradoSosClient()
    created_count = updated_count = queued_count = 0

    try:
        year = _current_even_year()

        from aggregation import ingest

        election_objs_by_type: dict[str, object] = {}

        for election_type in _ELECTION_TYPES:
            mapped = map_election(year, election_type)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source="co_sos",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1
            election_objs_by_type[election_type] = election_obj

        logger.info(
            "co_sos.sync_elections.seeded year=%d created=%d updated=%d",
            year, created_count, updated_count,
        )

        for election_type in _ELECTION_TYPES:
            try:
                fingerprint = client.get_candidate_page_fingerprint(election_type)
            except Exception as exc:
                logger.warning(
                    "co_sos.sync_elections.fingerprint_error election_type=%s err=%s",
                    election_type, exc,
                )
                continue

            if fingerprint is None:
                logger.info(
                    "co_sos.sync_elections.page_unavailable election_type=%s", election_type
                )
                continue

            cache_key = _PAGE_CACHE_KEY.format(election_type=election_type)
            last_fingerprint = cache.get(cache_key)

            if fingerprint == last_fingerprint:
                logger.info(
                    "co_sos.sync_elections.page_unchanged election_type=%s", election_type
                )
                continue

            election_obj = election_objs_by_type.get(election_type)
            if election_obj is None:
                logger.warning(
                    "co_sos.sync_elections.no_election_for_type election_type=%s year=%d",
                    election_type, year,
                )
                continue

            logger.info(
                "co_sos.sync_elections.page_updated election_type=%s fingerprint=%s",
                election_type, fingerprint,
            )
            sync_co_candidates.delay(election_obj.pk, election_type, fingerprint, cache_key)
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"Queued {queued_count} candidate sync(s)"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "queued": queued_count}

    except CoSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("co_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_co_candidates(
    self,
    election_pk: int,
    election_type: str,
    fingerprint: str,
    cache_key: str,
):
    """
    Stage 2: Parse the CO SOS candidate list HTML and upsert Race + Candidate records
    via the aggregation ingest service.

    After a successful sync, stores the page fingerprint in Redis so future
    Stage 1 runs skip unchanged pages.
    Also marks candidates absent from this run as WITHDRAWN.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("co_sos.sync_candidates.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="co_sos",
        task_name="sync_co_candidates",
        status=SyncLog.Status.STARTED,
    )
    client = ColoradoSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        html = client.fetch_candidate_html(election_type)
        candidates_raw = parse_candidate_table(html)

        if not candidates_raw:
            logger.info(
                "co_sos.sync_candidates.empty election=%s type=%s",
                election_obj.source_id or election_obj.pk, election_type,
            )
            sync_log.notes = "No candidates parsed from HTML"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0}

        is_primary = election_type == "primary"
        race_groups = build_race_groups(candidates_raw, is_primary=is_primary)

        from aggregation import ingest

        seen_candidate_pks: set[int] = set()
        seen_race_pks: set[int] = set()

        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            race_defaults.pop("canonical_key", None)
            race_defaults.pop("source", None)

            race_identity = {
                "office_title":    race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type":       race_defaults.pop("race_type"),
            }
            if not race_identity["office_title"]:
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source="co_sos",
                identity=race_identity,
                fields=race_defaults,
            )
            if race_obj.pk not in seen_race_pks:
                seen_race_pks.add(race_obj.pk)
                if race_was_new:
                    created_count += 1
                else:
                    updated_count += 1

            for raw_candidate in group["candidates"]:
                name = (raw_candidate.get("candidate_name") or "").strip()
                if not name:
                    continue
                cand_fields = map_candidate(raw_candidate)
                party = cand_fields.pop("party", "")
                cand_obj, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source="co_sos",
                    name=name,
                    party=party,
                    fields=cand_fields,
                )
                seen_candidate_pks.add(cand_obj.pk)
                if cand_was_new:
                    created_count += 1
                else:
                    updated_count += 1

        # Mark any previously-active candidates no longer in the page as WITHDRAWN
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj)
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(
            candidate_status=Candidate.CandidateStatus.WITHDRAWN
        )
        if withdrawn_count:
            logger.info(
                "co_sos.sync_candidates.withdrawn election=%s count=%d",
                election_obj.source_id or election_obj.pk, withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        cache.set(cache_key, fingerprint, _PAGE_CACHE_TTL)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"election_type={election_type} | withdrawn={withdrawn_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}

    except CoSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "co_sos.sync_candidates.failed election=%s",
            getattr(election_obj, "source_id", None) or getattr(election_obj, "pk", "?"),
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
