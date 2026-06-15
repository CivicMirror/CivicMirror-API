# backend/integrations/fl_ew/tasks.py
"""
Florida Election Watch Celery tasks.

Stage 1 — sync_fl_elections:
  Probe known FL election date slugs using a HEAD request.
  If the file exists, upsert the Election record and queue sync_fl_races.

Stage 2 — sync_fl_races:
  Fetch the tab-delimited results file for one election.
  Group rows into races (split by party for primaries).
  Upsert Race + Candidate records via aggregation ingest.

Trigger endpoint: POST /internal/tasks/sync-fl-ew/
"""
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import KNOWN_ELECTION_SLUGS, FlEwClient
from .exceptions import FlEwRetryableError
from .mappers import (
    build_race_groups,
    infer_election_type,
    map_candidate,
    map_election,
    map_race,
)
from .parsers import parse_results_file

logger = logging.getLogger(__name__)
_SOURCE = "fl_ew"


def _slug_to_date(slug: str):
    """Parse a YYYYMMDD slug into a date."""
    try:
        return datetime.strptime(slug, "%Y%m%d").date()
    except ValueError:
        return None


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_fl_elections(self):
    """Stage 1: Probe known FL election slugs and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_fl_elections",
        status=SyncLog.Status.STARTED,
    )
    client = FlEwClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        election_queue: list[tuple[str, object]] = []

        for slug in KNOWN_ELECTION_SLUGS:
            last_modified = client.get_last_modified(slug)
            if not last_modified:
                logger.info("fl_ew.sync_elections.not_published slug=%s", slug)
                skipped_count += 1
                continue

            election_date = _slug_to_date(slug)
            if election_date is None:
                logger.warning("fl_ew.sync_elections.bad_slug slug=%s", slug)
                skipped_count += 1
                continue

            mapped = map_election(slug, election_date)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}

            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )

            current_meta = dict(election_obj.source_metadata or {})
            if not current_meta.get("fl_ew_slug"):
                current_meta["fl_ew_slug"] = slug
                election_obj.source_metadata = current_meta
                election_obj.save(update_fields=["source_metadata"])

            if was_created:
                created_count += 1
            else:
                updated_count += 1

            election_queue.append((slug, election_obj))

        for idx, (slug, election_obj) in enumerate(election_queue):
            sync_fl_races.apply_async(
                args=[election_obj.pk, slug],
                countdown=idx * 5,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race sync(s); {skipped_count} slug(s) not yet published"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "queued": queued_count,
        }

    except Exception as exc:
        logger.exception("fl_ew.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_fl_races(self, election_pk: int, slug: str):
    """Stage 2: Fetch results file and upsert Race + Candidate records."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("fl_ew.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_fl_races",
        status=SyncLog.Status.STARTED,
    )
    client = FlEwClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        text = client.fetch_results_file(slug)
        rows = parse_results_file(text)

        if not rows:
            sync_log.notes = "File fetched but contained no data rows"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0}

        from aggregation import ingest

        is_primary = election_obj.election_type == "primary"
        race_groups = build_race_groups(rows, is_primary=is_primary)

        for group in race_groups:
            race_fields = map_race(election_obj, group)
            race_fields.pop("source", None)

            race_identity = {
                "office_title":    race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type":       race_fields.pop("race_type"),
            }

            if not race_identity["office_title"]:
                logger.warning(
                    "fl_ew.sync_races.null_title election=%s group=%r",
                    election_obj.source_id, group.get("race_name"),
                )
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source=_SOURCE,
                identity=race_identity,
                fields=race_fields,
            )
            if race_was_new:
                race_created += 1
            else:
                race_updated += 1

            seen_names: set[str] = set()
            for row in group["rows"]:
                name, party, fields = map_candidate(row)
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                _, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source=_SOURCE,
                    name=name,
                    party=party,
                    fields=fields,
                )
                if cand_was_new:
                    cand_created += 1
                else:
                    cand_updated += 1

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "status", "completed_at",
        ])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except FlEwRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("fl_ew.sync_races.failed election=%s slug=%s", election_pk, slug)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
