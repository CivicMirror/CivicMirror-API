"""
Election calendar Celery task.

seed_2026_elections:
    Seeds Election records for all 50 states — primary + general — from the
    static 2026 calendar (NCSL / FVAP).  Idempotent: safe to run multiple
    times.  Uses aggregation.ingest so deduplication by canonical key
    (state:type:date:jurisdiction_level) prevents duplicate records when a
    dedicated SOS integration has already seeded the same election.

    Status assignment:
        election_date <= today  → RESULTS_PENDING
        election_date > today   → UPCOMING

    Source precedence:
        "election_calendar" has no SourcePrecedence row, so it gets
        float('inf') rank (lowest priority).  It fills fields only when
        no higher-precedence source has claimed them.  Dedicated SOS
        integrations (co_sos, az_sos, etc.) always win.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .mappers import build_2026_election_specs

logger = logging.getLogger(__name__)

_SOURCE = "election_calendar"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def seed_2026_elections(self):
    """
    Seed all 50-state 2026 election calendar (primary + general).
    Idempotent — safe to re-run; existing records are updated via ingest.
    """
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="seed_2026_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        specs = build_2026_election_specs()
        today = timezone.localdate()
        created = updated = 0

        for spec in specs:
            status = (
                Election.Status.RESULTS_PENDING
                if spec.election_date <= today
                else Election.Status.UPCOMING
            )
            source_id = f"calendar_2026_{spec.state}_{spec.election_type}"

            _, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity={
                    "state": spec.state,
                    "election_type": spec.election_type,
                    "election_date": spec.election_date,
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": spec.name,
                    "status": status,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        logger.info(
            "election_calendar.seed_2026.done created=%d updated=%d total=%d",
            created, updated, len(specs),
        )

        sync_log.records_created = created
        sync_log.notes = f"updated={updated} total={len(specs)}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])

        return {"created": created, "updated": updated, "total": len(specs)}

    except Exception as exc:
        logger.exception("election_calendar.seed_2026.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)
