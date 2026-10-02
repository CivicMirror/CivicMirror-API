"""
Tennessee SOS Celery tasks.

Stage 1:
  sync_tn_elections    — parse the SOS election calendar, ingest statewide
                         elections, then queue sync_tn_candidates.
  sync_tn_candidates   — download the current qualified-candidate XLSX
                         workbooks and ingest races + candidates.
  sync_tn_result_index — index certified result documents from the SOS
                         results page into Election.source_metadata.

County/municipal calendar rows and live election-night polling are deferred
per docs/superpowers/plans/2026-07-14-tn-sos-adapter.md.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import TnSosClient
from .exceptions import TnSosRetryableError
from .mappers import is_in_scope_office, map_candidate, map_election, map_race
from .parsers import (
    document_checksum,
    parse_calendar,
    parse_candidate_workbook,
    parse_candidate_workbook_links,
    parse_results_index,
)

logger = logging.getLogger(__name__)

_FILENAME_DATE_RE = re.compile(r"^(\d{8})")


def _start_log(task_name: str) -> SyncLog:
    return SyncLog.objects.create(source="tn_sos", task_name=task_name, status=SyncLog.Status.STARTED)


def _finish_log(sync_log: SyncLog, created: int, updated: int) -> dict:
    sync_log.records_created = created
    sync_log.records_updated = updated
    sync_log.status = SyncLog.Status.COMPLETED
    sync_log.completed_at = timezone.now()
    sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
    return {"created": created, "updated": updated}


def _fail_log(sync_log: SyncLog, exc: Exception) -> None:
    sync_log.error_count = 1
    sync_log.last_error = str(exc)
    sync_log.status = SyncLog.Status.FAILED
    sync_log.completed_at = timezone.now()
    sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])


def _ingest_mapped_election(mapped: dict):
    from aggregation import ingest

    source_id = mapped.pop("source_id")
    identity = {
        "state": mapped["state"],
        "election_type": mapped["election_type"],
        "election_date": mapped["election_date"],
        "jurisdiction_level": mapped["jurisdiction_level"],
    }
    fields = {k: v for k, v in mapped.items() if k not in identity}
    return ingest.ingest_election(source="tn_sos", source_id=source_id, identity=identity, fields=fields)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tn_elections(self):
    sync_log = _start_log("sync_tn_elections")
    client = TnSosClient()
    created_count = updated_count = 0

    try:
        rows = parse_calendar(client.get_calendar_html())
        for row in rows:
            if not row.is_statewide:
                continue
            election_obj, was_created = _ingest_mapped_election(map_election(row))
            created_count += int(was_created)
            updated_count += int(not was_created)
            election_obj.last_synced_at = timezone.now()
            election_obj.save(update_fields=["last_synced_at"])

        sync_tn_candidates.delay()
        return _finish_log(sync_log, created_count, updated_count)

    except TnSosRetryableError as exc:
        _fail_log(sync_log, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("tn_sos.sync_tn_elections.failed")
        _fail_log(sync_log, exc)
        raise


def _target_election(election_pk: int | None):
    if election_pk is not None:
        return Election.objects.get(pk=election_pk)
    return (
        Election.objects.filter(
            state="TN",
            jurisdiction_level=Election.JurisdictionLevel.STATE,
            election_date__gte=timezone.localdate(),
        )
        .order_by("election_date")
        .first()
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tn_candidates(self, election_pk: int | None = None):
    sync_log = _start_log("sync_tn_candidates")
    client = TnSosClient()
    created_count = updated_count = 0

    try:
        from aggregation import ingest

        election_obj = _target_election(election_pk)
        if election_obj is None:
            logger.warning("tn_sos.sync_tn_candidates.no_upcoming_statewide_election")
            return _finish_log(sync_log, 0, 0)

        links = parse_candidate_workbook_links(client.get_candidate_list_html())
        workbooks_meta = []
        for link in links:
            content, final_url = client.download_file(link.url)
            checksum = document_checksum(content)
            workbooks_meta.append({"filename": link.filename, "url": final_url, "checksum": checksum})

            for record in parse_candidate_workbook(content, final_url):
                if not is_in_scope_office(record.office):
                    continue
                race_defaults = map_race(election_obj, record)
                race_identity = {
                    "office_title": race_defaults.pop("office_title"),
                    "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                    "race_type": race_defaults.pop("race_type"),
                }
                race_defaults.pop("source", None)
                race_obj, race_created = ingest.ingest_race(
                    election=election_obj, source="tn_sos",
                    identity=race_identity, fields=race_defaults,
                )
                created_count += int(race_created)
                updated_count += int(not race_created)

                cand_fields = map_candidate(record)
                name = cand_fields.pop("name")
                party = cand_fields.pop("party")
                _, cand_created = ingest.ingest_candidate(
                    race=race_obj, source="tn_sos", name=name, party=party, fields=cand_fields,
                )
                created_count += int(cand_created)
                updated_count += int(not cand_created)

        election_obj.source_metadata["tn_candidate_workbooks"] = workbooks_meta
        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["source_metadata", "last_synced_at"])
        return _finish_log(sync_log, created_count, updated_count)

    except TnSosRetryableError as exc:
        _fail_log(sync_log, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("tn_sos.sync_tn_candidates.failed")
        _fail_log(sync_log, exc)
        raise


# How far a results link's date may be from an election's date and still belong to it.
_RESULT_LINK_MATCH_WINDOW_DAYS = 7


def _link_dates(link) -> set:
    """
    Candidate dates for a results link: the page heading's date and the YYYYMMDD filename prefix.

    Neither is reliable on its own. sos.tn.gov headed the 2026-08-06 primary "August 1, 2026" while
    its files are named 20260806..., and the 2026-05-05 county primary's files are named 20260506...
    (the posting date). Matching uses both, within a tolerance window.
    """
    dates = set()
    if link.election_date is not None:
        dates.add(link.election_date)
    match = _FILENAME_DATE_RE.match(link.source_version)
    if match:
        try:
            dates.add(datetime.strptime(match.group(1), "%Y%m%d").date())
        except ValueError:
            pass
    return dates


def _match_election(link, elections):
    """
    Return the TN election nearest to any of the link's candidate dates, within the match window.
    Returns None when nothing is close enough, or when two elections are equally close (ambiguous).
    """
    dates = _link_dates(link)
    if not dates:
        return None
    scored = []
    for election_obj in elections:
        distance = min(abs((election_obj.election_date - d).days) for d in dates)
        if distance <= _RESULT_LINK_MATCH_WINDOW_DAYS:
            scored.append((distance, election_obj))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tn_result_index(self):
    sync_log = _start_log("sync_tn_result_index")
    client = TnSosClient()
    updated_count = 0

    try:
        links = parse_results_index(client.get_results_index_html())
        elections = list(Election.objects.filter(state="TN"))
        by_election: dict = {}
        for link in links:
            election_obj = _match_election(link, elections)
            if election_obj is None:
                continue
            by_election.setdefault(election_obj.pk, (election_obj, []))[1].append({
                "url": link.url,
                "label": link.label,
                "file_type": link.file_type,
                "result_level": link.result_level,
                "source_version": link.source_version,
            })

        for election_obj, entries in by_election.values():
            existing = election_obj.source_metadata.get("tn_result_links", [])
            existing_urls = {entry["url"] for entry in existing}
            new_entries = []
            for entry in entries:
                if entry["url"] not in existing_urls:
                    existing_urls.add(entry["url"])
                    new_entries.append(entry)
            if not new_entries:
                continue
            election_obj.source_metadata["tn_result_links"] = existing + new_entries
            election_obj.save(update_fields=["source_metadata"])
            updated_count += 1

        return _finish_log(sync_log, 0, updated_count)

    except TnSosRetryableError as exc:
        _fail_log(sync_log, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("tn_sos.sync_tn_result_index.failed")
        _fail_log(sync_log, exc)
        raise
