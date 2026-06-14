"""
Washington VoteWA Celery tasks.

Stage 1 — sync_wa_elections:
  Seed known WA election slugs from KNOWN_ELECTION_SLUGS.
  Fetch metadata for each from the VoteWA public API.
  Upsert Election records (enr_slug in source_metadata); queue sync_wa_races.

Stage 2 — sync_wa_races:
  Fetch state-level ballotItems[] from VoteWA /data endpoint.
  Upsert Race + Candidate or Race + MeasureOption via aggregation ingest.
  Schedule sync_wa_pdc_candidates after race sync completes.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election, MeasureOption
from ops.models import SyncLog

from .client import KNOWN_ELECTION_SLUGS, WaVoteWaClient
from .exceptions import WaVoteWaError, WaVoteWaRetryableError
from .mappers import _get_text, map_candidate, map_election, map_race

logger = logging.getLogger(__name__)
_SOURCE = "wa_votewa"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_wa_elections(self):
    """Stage 1: Seed known Washington elections and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_wa_elections",
        status=SyncLog.Status.STARTED,
    )
    client = WaVoteWaClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        election_objects: list[tuple[str, object]] = []

        for slug in KNOWN_ELECTION_SLUGS:
            try:
                meta = client.get_election_metadata(slug)
            except WaVoteWaError as exc:
                logger.warning("wa_votewa.sync_elections.meta_failed slug=%s: %s", slug, exc)
                skipped_count += 1
                continue

            mapped = map_election(slug, meta)
            if not mapped.get("election_date"):
                logger.warning("wa_votewa.sync_elections.no_date slug=%s", slug)
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            enr_slug_value = (fields.get("source_metadata") or {}).get("enr_slug", "")

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

            if enr_slug_value:
                current_meta = dict(election_obj.source_metadata or {})
                if not current_meta.get("enr_slug"):
                    current_meta["enr_slug"] = enr_slug_value
                    election_obj.source_metadata = current_meta
                    election_obj.save(update_fields=["source_metadata"])

            election_objects.append((slug, election_obj))

        for idx, (slug, election_obj) in enumerate(election_objects):
            sync_wa_races.apply_async(
                args=[election_obj.pk, slug],
                countdown=idx * 5,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs; {skipped_count} slugs skipped"
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
        logger.exception("wa_votewa.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_wa_races(self, election_pk: int, slug: str):
    """Stage 2: Fetch ballotItems and upsert Race + Candidate/MeasureOption."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("wa_votewa.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_wa_races",
        status=SyncLog.Status.STARTED,
    )
    client = WaVoteWaClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        data = client.get_election_data(slug)
        ballot_items = data.get("ballotItems") or []
        logger.info(
            "wa_votewa.sync_races election=%s ballot_items=%d",
            election_obj.source_id or election_obj.pk, len(ballot_items),
        )

        if not ballot_items:
            sync_log.notes = "No ballot items in /data response"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0}

        from aggregation import ingest

        for ballot_item in ballot_items:
            race_fields = map_race(election_obj, ballot_item, jurisdiction_slug="washington")
            race_fields.pop("source", None)
            race_identity = {
                "office_title":    race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type":       race_fields.pop("race_type"),
            }
            if not race_identity["office_title"]:
                logger.warning(
                    "wa_votewa.sync_races.null_title election=%s item_id=%s",
                    election_obj.source_id or election_obj.pk, ballot_item.get("id"),
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
                seen_names: set[str] = set()
                for opt in ballot_options:
                    name = _get_text(opt.get("name") or [])
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    cand_fields = map_candidate(opt)
                    party = cand_fields.pop("party", "")
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
                    label = _get_text(opt.get("name") or []) or opt.get("nativeId", "")
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

        try:
            from integrations.wa_pdc.tasks import sync_wa_pdc_candidates
            sync_wa_pdc_candidates.apply_async(args=[election_pk], countdown=10)
        except Exception:
            logger.warning(
                "wa_votewa.sync_races: could not schedule PDC enrichment for election %d",
                election_pk,
            )

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except WaVoteWaRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "wa_votewa.sync_races.failed election=%s slug=%s",
            election_obj.source_id or election_obj.pk, slug,
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
