"""
Virginia ELECT Celery tasks.

Stage 1 — sync_va_elections:
  Discover all ENR slugs from elections.virginia.gov.
  Fetch metadata for each slug from the Enhanced Voting API.
  Upsert Election records; enr_slug is stored in source_metadata (no manual admin entry needed).
  Queue sync_va_races for each election.

Stage 2 — sync_va_races:
  Fetch full ballotItems[] from Enhanced Voting /data endpoint.
  Upsert Race + Candidate (for Candidate contests) or Race + MeasureOption (for BallotMeasures).

Trigger endpoint: POST /internal/tasks/sync-va-elections/
"""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, MeasureOption, Race
from ops.models import SyncLog

from .client import VaElectClient
from .exceptions import VaElectRetryableError
from .mappers import _get_text, map_candidate, map_election, map_measure_option, map_race

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_va_elections(self):
    """
    Stage 1: Discover Virginia election slugs and upsert Election records.

    For each discovered slug, fetches lightweight metadata from Enhanced Voting
    and queues sync_va_races as a staggered subtask.
    """
    sync_log = SyncLog.objects.create(
        source="va_elect",
        task_name="sync_va_elections",
        status=SyncLog.Status.STARTED,
    )
    client = VaElectClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        slugs = client.get_election_slugs()
        logger.info("va_elect.sync_elections slugs_found=%d", len(slugs))

        if not slugs:
            sync_log.notes = "No slugs discovered from elections.virginia.gov"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "queued": 0}

        election_data: list[tuple[str, dict, str]] = []

        for slug in slugs:
            try:
                meta = client.get_election_metadata(slug)
            except VaElectRetryableError as exc:
                logger.warning("va_elect.sync_elections.meta_failed slug=%s: %s", slug, exc)
                skipped_count += 1
                continue

            mapped = map_election(slug, meta)
            if not mapped.get("election_date"):
                logger.warning("va_elect.sync_elections.no_date slug=%s", slug)
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            election_data.append((source_id, {**mapped, "last_synced_at": timezone.now()}, slug))

        source_ids = [d[0] for d in election_data]

        existing_source_ids = set(
            Election.objects.filter(source_id__in=source_ids).values_list("source_id", flat=True)
        ) if source_ids else set()

        election_objects = [
            Election(source_id=sid, **defaults)
            for sid, defaults, _ in election_data
        ]
        if election_objects:
            Election.objects.bulk_create(
                election_objects,
                update_conflicts=True,
                update_fields=[
                    "name", "election_date", "election_type", "jurisdiction_level",
                    "state", "status", "source_metadata", "last_synced_at",
                ],
                unique_fields=["source_id"],
            )

        created_count = sum(1 for sid, _, _ in election_data if sid not in existing_source_ids)
        updated_count = len(election_data) - created_count

        elections_by_source_id = {
            e.source_id: e
            for e in Election.objects.filter(source_id__in=source_ids)
        } if source_ids else {}

        for idx, (source_id, _, slug) in enumerate(election_data):
            election_obj = elections_by_source_id.get(source_id)
            if not election_obj:
                logger.warning("va_elect.sync_elections.missing_pk source_id=%s", source_id)
                continue
            # Stagger subtasks at 5-second intervals — /data responses are 1–3 MB each.
            sync_va_races.apply_async(
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

    except VaElectRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("va_elect.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_va_races(self, election_pk: int, slug: str):
    """
    Stage 2: Fetch all ballotItems for one election and upsert Race + Candidate/MeasureOption.

    All contests (statewide, district, ballot measures) are in the flat root-level
    ballotItems[] array — no locality nesting.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("va_elect.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="va_elect",
        task_name="sync_va_races",
        status=SyncLog.Status.STARTED,
    )
    client = VaElectClient()
    race_created = race_updated = cand_created = cand_updated = measure_created = measure_updated = 0

    try:
        data = client.get_election_data(slug)
        ballot_items = data.get("ballotItems") or []
        logger.info("va_elect.sync_races election=%s ballot_items=%d", election_obj.source_id, len(ballot_items))

        if not ballot_items:
            sync_log.notes = "No ballot items in /data response"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0, "measure_options": 0}

        now = timezone.now()

        race_objects: list[Race] = []
        # Store per-race ballot_item for candidate/measure creation after bulk upsert
        item_by_canonical_key: dict[str, dict] = {}

        for ballot_item in ballot_items:
            race_fields = map_race(election_obj, ballot_item)
            canonical_key = race_fields.pop("canonical_key")
            if not canonical_key:
                logger.warning("va_elect.sync_races.null_key election=%s item_id=%s",
                               election_obj.source_id, ballot_item.get("id"))
                continue

            race_objects.append(Race(
                canonical_key=canonical_key,
                election=election_obj,
                last_synced_at=now,
                **race_fields,
            ))
            item_by_canonical_key[canonical_key] = ballot_item

        canonical_keys = [r.canonical_key for r in race_objects]

        with transaction.atomic():
            existing_race_keys = set(
                Race.objects.filter(canonical_key__in=canonical_keys)
                .values_list("canonical_key", flat=True)
            ) if canonical_keys else set()

            Race.objects.bulk_create(
                race_objects,
                update_conflicts=True,
                update_fields=[
                    "election", "race_type", "office_title", "normalized_office_title",
                    "jurisdiction", "geography_scope", "certification_status", "source",
                    "race_status", "vote_method", "max_selections", "ocd_division_id",
                    "source_metadata", "last_synced_at",
                ],
                unique_fields=["canonical_key"],
            )
            race_created = sum(1 for r in race_objects if r.canonical_key not in existing_race_keys)
            race_updated = len(race_objects) - race_created

            races_by_key: dict[str, Race] = {
                r.canonical_key: r
                for r in Race.objects.filter(canonical_key__in=canonical_keys).only("id", "canonical_key", "race_type")
            } if canonical_keys else {}

            # --- Candidates ---
            seen_cand_keys: set[tuple[int, str]] = set()
            candidate_objects: list[Candidate] = []
            measure_objects: list[MeasureOption] = []

            for canonical_key, ballot_item in item_by_canonical_key.items():
                race = races_by_key.get(canonical_key)
                if not race:
                    continue

                ballot_options = (ballot_item.get("summaryResults") or {}).get("ballotOptions") or []

                if race.race_type == Race.RaceType.CANDIDATE:
                    for opt in ballot_options:
                        name = _get_text(opt.get("name") or [])
                        if not name:
                            continue
                        cand_key = (race.id, name)
                        if cand_key in seen_cand_keys:
                            continue
                        seen_cand_keys.add(cand_key)
                        candidate_objects.append(Candidate(
                            race=race,
                            name=name,
                            **map_candidate(opt),
                        ))

                elif race.race_type == Race.RaceType.MEASURE:
                    for opt in ballot_options:
                        label = _get_text(opt.get("name") or []) or opt.get("nativeId", "")
                        if not label:
                            continue
                        measure_objects.append(MeasureOption(
                            race=race,
                            **map_measure_option(opt),
                        ))

            if candidate_objects:
                existing_cand_keys = set(
                    Candidate.objects.filter(race__in=list(races_by_key.values()))
                    .values_list("race_id", "name")
                )
                cand_created = sum(
                    1 for c in candidate_objects
                    if (c.race.id, c.name) not in existing_cand_keys
                )
                cand_updated = len(candidate_objects) - cand_created
                Candidate.objects.bulk_create(
                    candidate_objects,
                    update_conflicts=True,
                    update_fields=["party", "incumbent", "candidate_status", "source_metadata"],
                    unique_fields=["race", "name"],
                )

            if measure_objects:
                existing_measure_keys = set(
                    MeasureOption.objects.filter(race__in=list(races_by_key.values()))
                    .values_list("race_id", "label")
                )
                measure_created = sum(
                    1 for m in measure_objects
                    if (m.race.id, m.label) not in existing_measure_keys
                )
                measure_updated = len(measure_objects) - measure_created
                MeasureOption.objects.bulk_create(
                    measure_objects,
                    update_conflicts=True,
                    update_fields=["source_metadata"],
                    unique_fields=["race", "label"],
                )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created + measure_created
        sync_log.records_updated = race_updated + cand_updated + measure_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
            "measure_options": {"created": measure_created, "updated": measure_updated},
        }

    except VaElectRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("va_elect.sync_races.failed election=%s slug=%s",
                         getattr(election_obj, "source_id", "?"), slug)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
