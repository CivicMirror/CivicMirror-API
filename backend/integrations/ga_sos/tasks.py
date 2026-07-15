from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election, MeasureOption
from ops.models import SyncLog

from .client import GaSosClient
from .exceptions import GaSosError, GaSosRetryableError
from .mappers import _get_text, map_candidate, map_election, map_measure_option, map_race

logger = logging.getLogger(__name__)
_SOURCE = "ga_sos"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ga_elections(self):
    """Discover Georgia Enhanced Voting elections and queue race/candidate syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_ga_elections",
        status=SyncLog.Status.STARTED,
    )
    client = GaSosClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        election_objects: list[tuple[str, object]] = []
        for row in client.list_elections():
            public_id = (row.get("publicElectionId") or "").strip()
            if not public_id:
                logger.warning("ga_sos.sync_elections.missing_public_id row=%s", row)
                skipped_count += 1
                continue

            mapped = map_election(row)
            if not mapped.get("election_date"):
                logger.warning("ga_sos.sync_elections.no_date public_id=%s", public_id)
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            source_metadata = fields.get("source_metadata") or {}

            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            current_meta = dict(election_obj.source_metadata or {})
            changed_meta = False
            for key in ("enr_slug", "ga_public_election_id", "jurisdiction_slug", "provider"):
                value = source_metadata.get(key)
                if value and not current_meta.get(key):
                    current_meta[key] = value
                    changed_meta = True
            if changed_meta:
                election_obj.source_metadata = current_meta
                election_obj.save(update_fields=["source_metadata"])

            election_objects.append((public_id, election_obj))

        for idx, (public_id, election_obj) in enumerate(election_objects):
            sync_ga_races.apply_async(args=[election_obj.pk, public_id], countdown=idx * 5)
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs; {skipped_count} elections skipped"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created",
            "records_updated",
            "records_skipped",
            "notes",
            "status",
            "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "queued": queued_count,
        }

    except GaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ga_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ga_races(self, election_pk: int, public_election_id: str):
    """Fetch one Georgia election's ballot items and upsert races/candidates."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("ga_sos.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_ga_races",
        status=SyncLog.Status.STARTED,
    )
    client = GaSosClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        data = client.get_election_data(public_election_id)
        ballot_items = data.get("ballotItems") or []
        logger.info(
            "ga_sos.sync_races election=%s ballot_items=%d",
            election_obj.source_id or election_obj.pk,
            len(ballot_items),
        )

        if not ballot_items:
            sync_log.notes = "No ballot items in /data response"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0}

        from aggregation import ingest

        for ballot_item in ballot_items:
            race_fields = map_race(election_obj, ballot_item)
            race_fields.pop("source", None)
            race_identity = {
                "office_title": race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type": race_fields.pop("race_type"),
            }
            if not race_identity["office_title"]:
                logger.warning(
                    "ga_sos.sync_races.null_title election=%s item_id=%s",
                    election_obj.source_id or election_obj.pk,
                    ballot_item.get("id"),
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

            ballot_options = (ballot_item.get("summaryResults") or {}).get("ballotOptions") or []
            if race_identity["race_type"] == "candidate":
                seen: set[tuple[str, str]] = set()
                for opt in ballot_options:
                    name = _get_text(opt.get("name") or [])
                    if not name:
                        continue
                    cand_fields = map_candidate(opt)
                    party = cand_fields.pop("party", "")
                    key = (name, party)
                    if key in seen:
                        continue
                    seen.add(key)
                    _, cand_was_new = ingest.ingest_candidate(
                        race=race_obj,
                        source=_SOURCE,
                        name=name,
                        party=party,
                        fields=cand_fields,
                    )
                    if cand_was_new:
                        cand_created += 1
                    else:
                        cand_updated += 1

            elif race_identity["race_type"] == "measure":
                for opt in ballot_options:
                    option_fields = map_measure_option(opt)
                    label = option_fields.get("option_label", "")
                    if not label:
                        continue
                    MeasureOption.objects.get_or_create(race=race_obj, option_label=label)

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except GaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except GaSosError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        return {"races": {"created": 0, "updated": 0}, "candidates": {"created": 0, "updated": 0}}

    except Exception as exc:
        logger.exception("ga_sos.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
