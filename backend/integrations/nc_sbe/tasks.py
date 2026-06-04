"""
NC State Board of Elections Celery tasks.

sync_nc_elections (Stage 1):
    Enumerate election folders from the public S3 bucket (dl.ncsbe.gov/ENRS/).
    Seed Election records for each discovered date, using a date-based heuristic
    to determine election_type.  Past elections are set to RESULTS_PENDING so
    that poll_pending_results will queue the NC results adapter.

    results_url is stored in Election.source_metadata so the NC results adapter
    can derive the S3 ZIP URL without requiring manual admin entry.

    Only elections from 2010 onward are seeded (older data is present but
    pre-dates CivicMirror's coverage scope).
"""
from __future__ import annotations

import datetime
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import NcSbeClient, _results_zip_url
from .exceptions import NcSbeRetryableError
from .mappers import election_name, election_type_from_date

logger = logging.getLogger(__name__)

_MIN_YEAR = 2010
_SOURCE = "nc_sbe"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_nc_elections(self):
    """
    Stage 1: Enumerate S3 ENRS/ folders and seed Election records.

    Sets results_url in source_metadata for each election so the NC results
    adapter can locate the ZIP without manual admin entry.
    """
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_nc_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        client = NcSbeClient()
        date_strs = client.list_election_date_strs()
        logger.info("nc_sbe.sync_elections.discovered count=%d", len(date_strs))

        created = updated = skipped = 0
        today = timezone.localdate()

        for date_str in date_strs:
            try:
                d = datetime.date(
                    int(date_str[0:4]),
                    int(date_str[5:7]),
                    int(date_str[8:10]),
                )
            except ValueError:
                logger.warning("nc_sbe.sync_elections.bad_date_str date_str=%s", date_str)
                continue

            if d.year < _MIN_YEAR:
                skipped += 1
                continue

            etype = election_type_from_date(d)
            source_id = f"nc_sbe_{date_str}"
            results_url = _results_zip_url(date_str)

            status = (
                Election.Status.RESULTS_PENDING
                if d <= today
                else Election.Status.UPCOMING
            )

            election, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity={
                    "state": "NC",
                    "election_type": etype,
                    "election_date": d,
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": election_name(d),
                    "status": status,
                    "source_metadata": {
                        "nc_date_str": date_str,
                        "results_url": results_url,
                    },
                },
            )
            if was_created:
                created += 1
            else:
                # Don't downgrade status for an already-certified or archived election.
                terminal_statuses = {Election.Status.RESULTS_CERTIFIED, Election.Status.ARCHIVED}
                if election.status not in terminal_statuses and election.status != status:
                    Election.objects.filter(pk=election.pk).update(status=status)
                updated += 1

        logger.info(
            "nc_sbe.sync_elections.done created=%d updated=%d skipped=%d",
            created, updated, skipped,
        )

        sync_log.records_created = created
        sync_log.notes = f"updated={updated} skipped_pre_{_MIN_YEAR}={skipped}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])

        return {"created": created, "updated": updated, "skipped": skipped}

    except NcSbeRetryableError as exc:
        logger.warning("nc_sbe.sync_elections.retryable_error: %s", exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("nc_sbe.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
