"""
Alabama SOS Celery tasks.

sync_al_elections (Stage 1a):
    Scrapes the year-specific Election Information page and upserts an
    Election row per heading, preserving official document links in
    source_metadata for future certification-parsing work.

sync_al_fcpa_candidates (Stage 1b):
    See mappers.py / parsers.py docstrings for the FCPA cycle-vs-election
    caveat. Populates Race + Candidate rows for Elections that have been
    manually tagged with source_metadata["al_fcpa_election_id"].
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from ops.models import SyncLog

from .client import AlSosClient
from .exceptions import AlSosRetryableError
from .parsers import parse_election_year_page

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_elections(self, year: int | None = None):
    """Stage 1a: upsert AL Election rows from the SOS year page."""
    from aggregation import ingest

    target_year = year or timezone.localdate().year
    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = AlSosClient()
        html = client.fetch_election_year_page(target_year)
        parsed = parse_election_year_page(html)

        created_count = 0
        for entry in parsed:
            election, created = ingest.ingest_election(
                source="al_sos",
                source_id=entry["source_id"],
                identity={
                    "state": "AL",
                    "election_type": entry["election_type"],
                    "election_date": entry["election_date"],
                    "jurisdiction_level": "state",
                },
                fields={
                    "name": entry["name"],
                    "source_metadata": {"al_document_links": entry["document_links"]},
                },
            )
            if created:
                created_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = len(parsed) - created_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"parsed": len(parsed), "created": created_count}

    except AlSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("al_sos.sync_al_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
