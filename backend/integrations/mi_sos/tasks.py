from __future__ import annotations

import logging
from datetime import date, datetime

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from core.cf_solver import CfSolverError
from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import MiSosClient
from .exceptions import MiSosRetryableError
from .mappers import (
    candidate_status,
    geography_scope,
    normalize_office_title,
    party_abbrev,
    split_running_mates,
)
from .parsers import parse_boe_candidate_listing, parse_mvic_elections

logger = logging.getLogger(__name__)

_MI_ELECTION_SPECS = [
    {
        "name": "2026 Michigan Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 8, 4),
        "boe_type": "PRI",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_primary",
    },
    {
        "name": "2026 Michigan General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "boe_type": "GEN",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_general",
    },
]


_MVIC_ID_KEY = "mi_mvic_election_id"


def _discover_mvic_election_ids(client: MiSosClient) -> dict[date, str]:
    """
    MVIC election id per election date, read from the vote-history dropdown.

    results/adapters/mi.py cannot fetch anything without this id — it reads
    Election.source_metadata["mi_mvic_election_id"] and returns no rows when the key
    is absent. Nothing used to write it, and parse_mvic_elections, which exists to
    read it, was never called, so Michigan's results adapter had never run.

    Deliberately non-fatal: candidate ingestion below comes from an entirely separate
    BOE host, and MVIC being unreachable (CF solver down or unconfigured) must not
    stop Michigan's ballot from syncing. Costs one CF solve per run; fetch_through_cf
    caches for 25 minutes and this task runs daily, so no pre-check is worth it.
    """
    try:
        html = client.fetch_votehistory_page()
    except (MiSosRetryableError, CfSolverError) as exc:
        logger.warning("mi_sos.mvic_discovery_unavailable err=%s", exc)
        return {}

    try:
        rows = parse_mvic_elections(html)
    except Exception:
        # Broad on purpose: a shape change in MVIC's page must degrade this enrichment
        # step, never take the BOE candidate sync down with it.
        logger.exception("mi_sos.mvic_discovery_parse_failed")
        return {}

    ids: dict[date, str] = {}
    for row in rows:
        raw_date = (row.get("date") or "").strip()
        if not raw_date:
            continue
        try:
            # MVIC writes "5/5/2026" unpadded; strptime accepts padded and unpadded alike.
            parsed = datetime.strptime(raw_date, "%m/%d/%Y").date()
        except ValueError:
            logger.warning("mi_sos.mvic_unparseable_date value=%r", raw_date)
            continue
        if parsed in ids:
            logger.warning(
                "mi_sos.mvic_duplicate_date date=%s keeping=%s ignoring=%s",
                parsed, ids[parsed], row.get("election_id"),
            )
            continue
        ids[parsed] = row["election_id"]
    logger.info("mi_sos.mvic_discovery_done elections=%d", len(ids))
    return ids


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_mi_elections(self=None):
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="mi_sos",
        task_name="sync_mi_elections",
        status=SyncLog.Status.STARTED,
    )
    created = updated = 0
    client = MiSosClient()

    try:
        mvic_ids = _discover_mvic_election_ids(client)
        for spec in _MI_ELECTION_SPECS:
            source_metadata = {
                "mi_boe_election_type": spec["boe_type"],
                "mi_boe_election_year": spec["boe_year"],
            }
            mvic_id = mvic_ids.get(spec["election_date"])
            if mvic_id:
                source_metadata[_MVIC_ID_KEY] = mvic_id
            election, _ = ingest.ingest_election(
                source="mi_sos",
                source_id=spec["source_id"],
                identity={
                    "state": "MI",
                    "election_type": spec["election_type"],
                    "election_date": spec["election_date"],
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": spec["name"],
                    "status": (
                        Election.Status.UPCOMING
                        if spec["election_date"] > timezone.localdate()
                        else Election.Status.RESULTS_PENDING
                    ),
                    "source_metadata": source_metadata,
                },
            )
            if mvic_id and (election.source_metadata or {}).get(_MVIC_ID_KEY) != mvic_id:
                # A higher-precedence source owns source_metadata, so the id did not
                # land and results for this election will still fetch nothing.
                logger.warning(
                    "mi_sos.mvic_id_not_applied election=%s date=%s mvic_id=%s",
                    election.pk, spec["election_date"], mvic_id,
                )

            rows = parse_boe_candidate_listing(
                client.fetch_candidate_listing(spec["boe_type"], spec["boe_year"])
            )
            seen: set[int] = set()
            for row in rows:
                office_title = normalize_office_title(row["office_title"])
                race, race_created = ingest.ingest_race(
                    election=election,
                    source="mi_sos",
                    identity={
                        "office_title": office_title,
                        "ocd_division_id": "",
                        "race_type": Race.RaceType.CANDIDATE,
                    },
                    fields={
                        "jurisdiction": "Michigan",
                        # Previously omitted, which left every MI race with a blank
                        # geography_scope and made statewide filters miss Michigan.
                        "geography_scope": geography_scope(office_title),
                        "source_metadata": {"mi_office_raw": row["office_title"]},
                    },
                )
                created += int(race_created)

                # Store the top of the ticket, not the joint ballot line, so MVIC's
                # result rows match. The full line stays in source_metadata.
                candidate_name, running_mates = split_running_mates(row["candidate_name"])
                cand, cand_created = ingest.ingest_candidate(
                    race=race,
                    source="mi_sos",
                    name=candidate_name,
                    party=party_abbrev(row["party"]),
                    fields={
                        "candidate_status": candidate_status(row["status"]),
                        "incumbent": bool(row["incumbent"]),
                        "source_metadata": {
                            "mi_ballot_name": row["candidate_name"],
                            "mi_running_mates": running_mates,
                            "mi_candidate_status_raw": row["status"],
                            "mi_filing_method": row["filing_method"],
                            "mi_candidate_address": row["candidate_address"],
                            "mi_filed_on": row["filed_on"],
                            "mi_incumbent_raw": row["incumbent"],
                        },
                    },
                )
                seen.add(cand.pk)
                created += int(cand_created)
                updated += int(not cand_created)

            Candidate.objects.filter(
                race__election=election,
                race__source="mi_sos",
                candidate_status=Candidate.CandidateStatus.RUNNING,
            ).exclude(pk__in=seen).update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

            election.last_synced_at = timezone.now()
            election.save(update_fields=["last_synced_at"])

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"created": created, "updated": updated}
    except MiSosRetryableError as exc:
        if self is None:
            raise
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
        except MiSosRetryableError:
            sync_log.error_count = 1
            sync_log.last_error = str(exc)
            sync_log.status = SyncLog.Status.FAILED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
            raise
    except Exception as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
