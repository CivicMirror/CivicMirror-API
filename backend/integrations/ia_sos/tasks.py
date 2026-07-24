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
import re
from urllib.parse import unquote

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import IowaSosClient
from .exceptions import IowaSosRetryableError
from .mappers import (
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


def _candidate_pdf_year(info: dict) -> int | None:
    text = " ".join(
        str(value or "")
        for value in (
            info.get("url"),
            info.get("last_modified"),
        )
    )
    decoded = unquote(text)
    match = re.search(r"\b(20\d{2})\b", decoded)
    if not match:
        return None
    return int(match.group(1))


def _candidate_election_key(election_type: str, election_year: int) -> tuple[str, int]:
    return election_type, election_year


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
        from aggregation import ingest

        # --- Track 1: parse calendar PDF → upsert Elections via ingest ---
        try:
            pdf_bytes = client.fetch_calendar_pdf()
            parsed_elections = parse_calendar_pdf(pdf_bytes)
        except IowaSosRetryableError as exc:
            raise self.retry(exc=exc)
        except Exception as exc:
            logger.error("ia_sos.sync_elections.calendar_fetch_failed: %s", exc)
            parsed_elections = []

        election_objs_by_key: dict[tuple[str, int], object] = {}

        for parsed in parsed_elections:
            mapped = map_election(parsed)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source="ia_sos",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1
            election_key = _candidate_election_key(
                mapped["election_type"], parsed["election_year"]
            )
            election_objs_by_key[election_key] = election_obj

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

            pdf_year = _candidate_pdf_year(info)
            if pdf_year is None:
                logger.warning(
                    "ia_sos.sync_elections.no_pdf_year election_type=%s url=%s",
                    election_type,
                    info["url"],
                )
                continue

            election_obj = election_objs_by_key.get(
                _candidate_election_key(election_type, pdf_year)
            )
            if election_obj is None:
                logger.warning(
                    "ia_sos.sync_elections.no_election_for_type election_type=%s year=%s "
                    "— calendar parse may have missed it",
                    election_type,
                    pdf_year,
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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ia_candidates(self, election_pk: int, pdf_url: str, fingerprint: str, cache_key: str):
    """
    Stage 2: Parse the Iowa SOS candidate list PDF and upsert Race + Candidate records
    via the aggregation ingest service.

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
                election_obj.source_id or election_obj.pk, pdf_url,
            )
            sync_log.notes = "No candidates parsed from PDF"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0}

        race_groups = build_race_groups(election_obj.name, candidates_raw)

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
                source="ia_sos",
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
                    source="ia_sos",
                    name=name,
                    party=party,
                    fields=cand_fields,
                )
                seen_candidate_pks.add(cand_obj.pk)
                if cand_was_new:
                    created_count += 1
                else:
                    updated_count += 1

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
                election_obj.source_id or election_obj.pk, withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        cache.set(cache_key, fingerprint, _PDF_CACHE_TTL)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"pdf_url={pdf_url} | withdrawn={withdrawn_count}"
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
        logger.exception(
            "ia_sos.sync_candidates.failed election=%s",
            getattr(election_obj, "source_id", None) or getattr(election_obj, "pk", "?"),
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
