"""
Maryland SBE Celery tasks.

sync_md_elections (Stage 1a): seed Election records for MD's active cycle
    from the maintained calendar.py table.

sync_md_races (Stage 1b): fetch the active cycle's consolidated statewide
    candidate-list CSV and upsert Race + Candidate records for in-scope
    (federal + state legislative + state executive) offices. See mappers.py
    for scope and ticket-name handling.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .calendar import get_active_cycle
from .client import MdSbeClient
from .exceptions import MdSbeRetryableError
from .mappers import (
    candidate_display_name,
    group_candidate_rows,
    is_in_scope_office,
    map_candidate,
    map_race_identity,
    parse_statewide_candidate_csv,
)

logger = logging.getLogger(__name__)

_SOURCE = "md_sbe"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_md_elections(self):
    """Stage 1a: seed MD's primary and general Election rows from the calendar table."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_md_elections", status=SyncLog.Status.STARTED,
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
                    source_id=f"md_sbe_{cycle.year}_{phase}",
                    identity={
                        "state": "MD",
                        "election_type": phase,
                        "election_date": election_date,
                        "jurisdiction_level": Election.JurisdictionLevel.STATE,
                    },
                    fields={
                        "name": f"{cycle.year} Maryland {phase.title()} Election",
                        "status": status,
                        "source_metadata": {
                            "cycle_prefix": cycle.prefix_for_phase(phase),
                            "phase": phase,
                        },
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
        logger.exception("md_sbe.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_md_races(self):
    """Stage 1b: upsert Race + Candidate records from the active cycle's candidate CSV."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_md_races", status=SyncLog.Status.STARTED,
    )
    try:
        today = timezone.localdate()
        cycle = get_active_cycle(today)
        if cycle is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "no active MD cycle configured"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_out_of_scope": 0}

        phase = cycle.phase_for_date(today)
        election_type = phase
        election = Election.objects.filter(
            state="MD", election_type=election_type, election_date=(
                cycle.primary_date if phase == "primary" else cycle.general_date
            ),
        ).first()
        if election is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "sync_md_elections has not run yet for this cycle"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_out_of_scope": 0}

        client = MdSbeClient()
        csv_text = client.fetch_statewide_candidate_csv(
            year=cycle.year, cycle_prefix=cycle.prefix_for_phase(phase), phase=phase,
        )
        rows = parse_statewide_candidate_csv(csv_text)
        # Primary contests are one race PER PARTY (MD groups every party's
        # candidates under one Office Name/district row-set); general contests
        # are one race spanning all parties' nominees. See group_candidate_rows.
        groups = group_candidate_rows(rows, split_by_party=(phase == "primary"))

        created = updated = skipped_out_of_scope = 0

        for (office_name, district, party), group_rows in groups.items():
            if not is_in_scope_office(office_name):
                skipped_out_of_scope += 1
                continue

            identity, fields = map_race_identity(office_name, district, party)
            race, race_created = ingest.ingest_race(
                election=election, source=_SOURCE, identity=identity, fields=fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for row in group_rows:
                name = candidate_display_name(row)
                if not name:
                    continue
                ingest.ingest_candidate(
                    race=race, source=_SOURCE, name=name,
                    party=(row.get("Office Political Party") or "").strip(),
                    fields=map_candidate(row),
                )

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"skipped_out_of_scope={skipped_out_of_scope}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "skipped_out_of_scope": skipped_out_of_scope}

    except MdSbeRetryableError as exc:
        logger.warning("md_sbe.sync_races.retryable_error: %s", exc)
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
        logger.exception("md_sbe.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
