"""
Utah elections Celery tasks.

sync_ut_elections (Stage 1a): seed Election records for UT's active cycle
    from the maintained calendar.py table.

sync_ut_races (Stage 1b): fetch the active cycle's Candidate Filing Excel
    workbook and upsert Race + Candidate records for in-scope (federal +
    state legislative + state executive) sections. See mappers.py for scope,
    status mapping, and name-casing.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .calendar import get_active_cycle
from .client import UtElectionsClient
from .exceptions import UtElectionsRetryableError
from .mappers import (
    map_candidate,
    map_race_identity,
    parse_candidate_filing_workbook,
    titlecase_name,
)

logger = logging.getLogger(__name__)

_SOURCE = "ut_elections"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ut_elections(self):
    """Stage 1a: seed UT's primary and general Election rows from the calendar table."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_ut_elections", status=SyncLog.Status.STARTED,
    )
    try:
        from aggregation import ingest

        today = timezone.localdate()
        cycle = get_active_cycle(today)
        created = updated = 0

        if cycle is not None:
            for phase, election_date in (("primary", cycle.primary_date), ("general", cycle.general_date)):
                status = (
                    Election.Status.RESULTS_PENDING if election_date <= today
                    else Election.Status.UPCOMING
                )
                election, was_created = ingest.ingest_election(
                    source=_SOURCE,
                    source_id=f"ut_elections_{cycle.year}_{phase}",
                    identity={
                        "state": "UT",
                        "election_type": phase,
                        "election_date": election_date,
                        "jurisdiction_level": Election.JurisdictionLevel.STATE,
                    },
                    fields={
                        "name": f"{cycle.year} Utah {phase.title()} Election",
                        "status": status,
                        "source_metadata": {"phase": phase},
                    },
                )
                created += int(was_created)
                updated += int(not was_created)

        sync_log.records_created = created
        sync_log.notes = f"updated={updated}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])
        return {"created": created, "updated": updated}

    except Exception as exc:
        logger.exception("ut_elections.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ut_races(self):
    """Stage 1b: upsert Race + Candidate records from the active cycle's Candidate Filing workbook."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_ut_races", status=SyncLog.Status.STARTED,
    )
    try:
        today = timezone.localdate()
        cycle = get_active_cycle(today)
        if cycle is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "no active UT cycle configured"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_no_election": 0}

        phase = "primary" if today <= cycle.primary_date else "general"
        election = Election.objects.filter(
            state="UT", election_type=phase, election_date=(
                cycle.primary_date if phase == "primary" else cycle.general_date
            ),
        ).first()
        if election is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "sync_ut_elections has not run yet for this cycle"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_no_election": 0}

        client = UtElectionsClient()
        workbook_bytes = client.fetch_candidate_filing_workbook(cycle.candidate_filing_url)
        rows = parse_candidate_filing_workbook(workbook_bytes)

        # Group already-in-scope rows by Office; parse_candidate_filing_workbook
        # filters out-of-scope sections before this point.
        offices: dict[str, list[dict]] = {}
        for row in rows:
            offices.setdefault(row["office"], []).append(row)

        created = updated = candidates_skipped = 0

        for office, office_rows in offices.items():
            identity, fields = map_race_identity(office)
            race, race_created = ingest.ingest_race(
                election=election, source=_SOURCE, identity=identity, fields=fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for row in office_rows:
                candidate_fields = map_candidate(row)
                if candidate_fields is None:
                    candidates_skipped += 1
                    continue
                ingest.ingest_candidate(
                    race=race, source=_SOURCE, name=titlecase_name(row["name"]),
                    party=row["party"], fields=candidate_fields,
                )

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"candidates_skipped={candidates_skipped}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "candidates_skipped": candidates_skipped}

    except UtElectionsRetryableError as exc:
        logger.warning("ut_elections.sync_races.retryable_error: %s", exc)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
    except Exception as exc:
        logger.exception("ut_elections.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
