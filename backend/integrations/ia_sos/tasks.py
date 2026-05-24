"""
Iowa SOS Celery tasks.

Stage 1 — sync_ia_elections:
  Parse the 3-year calendar PDF → upsert Election records.
  For each configured election type (primary / general), check whether
  a new candidate list PDF has been published (via ETag / Last-Modified).
  If so, queue sync_ia_candidates for that election.

Stage 2 — sync_ia_candidates:
  Download + parse the candidate list PDF for one election.
  Upsert Race + Candidate records.
  Mark candidates absent from this run as WITHDRAWN.
"""
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import IowaSosClient
from .exceptions import IowaSosRetryableError
from .mappers import (
    build_race_canonical_key,
    build_race_groups,
    map_candidate,
    map_election,
    map_race,
)
from .parsers import parse_calendar_pdf, parse_candidate_list_pdf

logger = logging.getLogger(__name__)

# Cache key prefix for last-seen candidate PDF fingerprint (url|etag|last_modified)
_PDF_CACHE_KEY = "ia_sos:candidate_pdf_fingerprint:{election_type}"
_PDF_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days


def _pdf_fingerprint(info: dict) -> str:
    return f"{info['url']}|{info['etag']}|{info['last_modified']}"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ia_elections(self):
    """
    Stage 1: Sync Iowa election records from the SOS calendar PDF and
    check for updated candidate list PDFs to queue Stage 2.
    """
    sync_log = SyncLog.objects.create(
        source="ia_sos",
        task_name="sync_ia_elections",
        status=SyncLog.Status.STARTED,
    )
    client = IowaSosClient()
    created_count = updated_count = queued_count = 0

    try:
        # --- Track 1: parse calendar PDF → upsert Elections ---
        try:
            pdf_bytes = client.fetch_calendar_pdf()
            parsed_elections = parse_calendar_pdf(pdf_bytes)
        except IowaSosRetryableError as exc:
            raise self.retry(exc=exc)
        except Exception as exc:
            logger.error("ia_sos.sync_elections.calendar_fetch_failed: %s", exc)
            parsed_elections = []

        for parsed in parsed_elections:
            mapped = map_election(parsed)
            source_id = mapped.pop("source_id")
            _, created = Election.objects.update_or_create(
                source_id=source_id,
                defaults={**mapped, "last_synced_at": timezone.now()},
            )
            created_count += int(created)
            updated_count += int(not created)

        logger.info(
            "ia_sos.sync_elections.calendar created=%d updated=%d",
            created_count, updated_count,
        )

        # --- Track 2: check for updated candidate PDFs ---
        for election_type in ("primary", "general"):
            try:
                info = client.get_candidate_pdf_info(election_type)
            except Exception as exc:
                logger.warning(
                    "ia_sos.sync_elections.candidate_page_error election_type=%s err=%s",
                    election_type, exc,
                )
                continue

            if info is None:
                logger.info(
                    "ia_sos.sync_elections.no_candidate_pdf election_type=%s", election_type
                )
                continue

            fingerprint = _pdf_fingerprint(info)
            cache_key = _PDF_CACHE_KEY.format(election_type=election_type)
            last_fingerprint = cache.get(cache_key)

            if fingerprint == last_fingerprint:
                logger.info(
                    "ia_sos.sync_elections.pdf_unchanged election_type=%s", election_type
                )
                continue

            # Find or create the matching Election for this type
            election_obj = _resolve_election_for_type(election_type)
            if election_obj is None:
                logger.warning(
                    "ia_sos.sync_elections.no_election_for_type election_type=%s "
                    "— calendar parse may have missed it",
                    election_type,
                )
                continue

            logger.info(
                "ia_sos.sync_elections.pdf_updated election_type=%s url=%s",
                election_type, info["url"],
            )
            sync_ia_candidates.delay(election_obj.pk, info["url"], fingerprint, cache_key)
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

    except IowaSosRetryableError:
        raise
    except Exception as exc:
        logger.exception("ia_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


def _resolve_election_for_type(election_type: str) -> Election | None:
    """
    Find the most relevant upcoming/active Iowa election matching the given type.
    Looks for source_ids like 'ia_sos_2026_primary' in descending date order.
    """
    from django.utils import timezone as tz
    today = tz.localdate()
    return (
        Election.objects.filter(
            state="IA",
            source_id__startswith="ia_sos_",
            source_id__contains=election_type,
            election_date__gte=today,
        )
        .order_by("election_date")
        .first()
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ia_candidates(self, election_pk: int, pdf_url: str, fingerprint: str, cache_key: str):
    """
    Stage 2: Parse the Iowa SOS candidate list PDF and upsert Race + Candidate records.

    After successful sync, updates the cache fingerprint so repeated runs
    do not re-fetch an unchanged PDF.
    Also marks candidates absent from this run as WITHDRAWN.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("ia_sos.sync_candidates.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="ia_sos",
        task_name="sync_ia_candidates",
        status=SyncLog.Status.STARTED,
    )
    client = IowaSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        pdf_bytes = client.fetch_pdf(pdf_url)
        candidates_raw = parse_candidate_list_pdf(pdf_bytes)

        if not candidates_raw:
            logger.info(
                "ia_sos.sync_candidates.empty election=%s url=%s",
                election_obj.source_id, pdf_url,
            )
            sync_log.notes = "No candidates parsed from PDF"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0}

        race_groups = build_race_groups(election_obj.name, candidates_raw)
        seen_candidate_pks: set[int] = set()

        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            canonical_key = race_defaults.pop("canonical_key")

            race, race_created = Race.objects.update_or_create(
                canonical_key=canonical_key,
                defaults={"election": election_obj, **race_defaults, "last_synced_at": timezone.now()},
            )
            created_count += int(race_created)
            updated_count += int(not race_created)

            for raw_candidate in group["candidates"]:
                name = (raw_candidate.get("candidate_name") or "").strip()
                if not name:
                    continue
                cand_obj, cand_created = Candidate.objects.update_or_create(
                    race=race,
                    name=name,
                    defaults=map_candidate(raw_candidate),
                )
                seen_candidate_pks.add(cand_obj.pk)
                created_count += int(cand_created)
                updated_count += int(not cand_created)

        # Mark previously-active candidates no longer in the PDF as WITHDRAWN
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
                "ia_sos.sync_candidates.withdrawn election=%s count=%d",
                election_obj.source_id, withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        # Record the fingerprint so we skip unchanged PDFs in future runs
        cache.set(cache_key, fingerprint, _PDF_CACHE_TTL)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = (
            f"pdf_url={pdf_url} | withdrawn={withdrawn_count}"
        )
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}

    except IowaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ia_sos.sync_candidates.failed election=%s", election_obj.source_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
