"""
New Jersey elections Celery tasks.

Stage 1 enrichment — sync_nj_county_urls:
  NJ has no custom election/race creation (Stage 1 stays on the existing
  Google Civic API sync). This task only enriches already-existing NJ
  Election rows with the current per-county Clarity URLs/IDs, scraped from
  the state's election-night-results page, so Stage 2 (results/adapters/
  nj.py) knows which counties to poll and with what election ID.

  Only elections with status ACTIVE or RESULTS_PENDING are enriched —
  the results page only ever reflects "the current" election, so applying
  it to archived/upcoming elections would be meaningless or wrong.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import NewJerseyElectionsClient
from .exceptions import NjElectionsRetryableError
from .parsers import classify_clarity_counties, parse_county_urls

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (Election.Status.ACTIVE, Election.Status.RESULTS_PENDING)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_nj_county_urls(self):
    """Scrape the NJ ENR county table and attach it to active NJ elections."""
    sync_log = SyncLog.objects.create(
        source="nj_elections",
        task_name="sync_nj_county_urls",
        status=SyncLog.Status.STARTED,
    )
    client = NewJerseyElectionsClient()
    updated_count = 0

    try:
        elections = list(Election.objects.filter(state="NJ", status__in=_ACTIVE_STATUSES))
        if not elections:
            sync_log.notes = "No active NJ elections to enrich"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"updated": 0}

        html = client.fetch_enr_page()
        county_urls = parse_county_urls(html)
        clarity_counties = classify_clarity_counties(county_urls)

        for election in elections:
            meta = election.source_metadata or {}
            meta["nj_county_urls"] = clarity_counties
            election.source_metadata = meta
            election.last_synced_at = timezone.now()
            election.save(update_fields=["source_metadata", "last_synced_at"])
            updated_count += 1

        sync_log.records_updated = updated_count
        sync_log.notes = f"clarity_counties={len(clarity_counties)}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_updated", "notes", "status", "completed_at",
        ])
        return {"updated": updated_count}

    except NjElectionsRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("nj_elections.sync_county_urls.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
