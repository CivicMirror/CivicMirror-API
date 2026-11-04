"""
Alaska Division of Elections Celery tasks.

sync_ak_races (Stage 1): scrape elections.alaska.gov/election-candidates/
    and upsert Race + Candidate records for Alaska's primary election.

Primary only, not general -- a deliberate scope decision (issue #233).
elections.alaska.gov/election-candidates/ has no real per-election filter
(confirmed live: every Election/Contest selection returns the same full
2026-cycle candidate roster -- see mappers.py docstring), so it lists
everyone who *filed*, not who's actually on a given ballot. For the
primary that's correct: every filer appears on Alaska's blanket primary
ballot. For the general it would be wrong -- only the top 4 per office
advance past the primary (confirmed against the live results CSV: 17
people filed for Governor, only 4 have vote rows), and this page has no
field that distinguishes "didn't advance" from "still running." The
general's candidates are already covered correctly by
results/tasks.py's bootstrap-from-results-feed path, which only ever sees
the candidates who actually have vote rows. Keeping this scraper's output
as a record of everyone who filed for the cycle (useful on its own, and for
anyone who refiles in a future election) rather than feeding it into the
general is the chosen tradeoff; see the issue discussion.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from ops.models import SyncLog

from .client import AkSosClient
from .exceptions import AkSosRetryableError
from .mappers import CONTESTS_IN_SCOPE, map_candidate, map_race_identity, parse_candidates_html

logger = logging.getLogger(__name__)

_SOURCE = "ak_sos"
_ELECTION_NAME = "2026 Primary Election"
# Any value in CONTESTS_IN_SCOPE works identically (see mappers.py docstring);
# this one is just first in the site's own Contest dropdown.
_SEARCH_CONTEST = CONTESTS_IN_SCOPE[0]


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ak_races(self):
    """Stage 1: upsert Race + Candidate records from Alaska's candidate-filing page."""
    from elections.models import Election

    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_ak_races", status=SyncLog.Status.STARTED,
    )
    try:
        election = Election.objects.filter(
            state="AK", election_type=Election.ElectionType.PRIMARY,
        ).exclude(status__in=Election.TERMINAL_STATUSES).order_by("-election_date").first()
        if election is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "no non-terminal AK primary election found"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0}

        with AkSosClient() as client:
            html = client.fetch_candidates_html(_ELECTION_NAME, _SEARCH_CONTEST)
        records = parse_candidates_html(html)

        offices: dict[str, list[dict]] = {}
        for record in records:
            offices.setdefault(record["office_title"], []).append(record)

        from aggregation import ingest

        created = updated = 0
        for office_title, office_records in offices.items():
            identity, fields = map_race_identity(office_title)
            race, race_created = ingest.ingest_race(
                election=election, source=_SOURCE, identity=identity, fields=fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for record in office_records:
                ingest.ingest_candidate(
                    race=race, source=_SOURCE, name=record["name"], party=record["party"],
                    fields=map_candidate(record),
                )

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"offices={len(offices)} candidates={len(records)}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "candidates": len(records)}

    except AkSosRetryableError as exc:
        logger.warning("ak_sos.sync_races.retryable_error: %s", exc)
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
        logger.exception("ak_sos.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
