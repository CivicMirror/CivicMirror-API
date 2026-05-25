import logging
from datetime import date as _date

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, MeasureOption, Race
from ops.models import SyncLog

from .client import VremsClient
from .exceptions import SCVremsRetryableError
from .mappers import (
    build_race_groups,
    is_filing_open,
    is_referendum,
    map_candidate,
    map_election,
    map_race,
)

logger = logging.getLogger(__name__)

# Limit to current and next calendar year by default.
# Pass years=[...] explicitly to sync_sc_elections for historical backfill.
_DEFAULT_YEARS = None  # resolved dynamically at task runtime — see sync_sc_elections


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sc_elections(self, years: list[int] | None = None):
    """
    Stage 1: Fetch all SC elections from VREMS and upsert into the Election model.

    For each election where filing is open, queues sync_sc_races as a staggered
    subtask. Referendum elections (filingPeriodBeginDate=null) get Election records
    but no race sync (no candidate data available from VREMS).
    """
    sync_log = SyncLog.objects.create(
        source="sc_vrems",
        task_name="sync_sc_elections",
        status=SyncLog.Status.STARTED,
    )
    client = VremsClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        elections = client.get_all_elections(years=years or [_date.today().year, _date.today().year + 1])
        logger.info("sc_vrems.sync_elections found=%d", len(elections))

        # Build all Election objects in memory first.
        election_data: list[tuple[str, dict, dict]] = []
        for vrems_election in elections:
            mapped = map_election(vrems_election)
            source_id = mapped.pop("source_id")
            election_data.append((source_id, {**mapped, "last_synced_at": timezone.now()}, vrems_election))

        source_ids = [d[0] for d in election_data]

        # Pre-fetch existing source_ids for create/update accounting (1 query).
        existing_source_ids = set(
            Election.objects.filter(source_id__in=source_ids).values_list("source_id", flat=True)
        ) if source_ids else set()

        # Bulk upsert all elections in one query.
        election_objects = [
            Election(source_id=sid, **defaults)
            for sid, defaults, _ in election_data
        ]
        Election.objects.bulk_create(
            election_objects,
            update_conflicts=True,
            update_fields=["name", "election_date", "jurisdiction_level", "state", "status", "last_synced_at"],
            unique_fields=["source_id"],
        )
        created_count = sum(1 for sid, _, _ in election_data if sid not in existing_source_ids)
        updated_count = len(election_data) - created_count

        # Fetch back with PKs so subtasks can reference election.pk.
        elections_by_source_id = {
            e.source_id: e
            for e in Election.objects.filter(source_id__in=source_ids)
        } if source_ids else {}

        for idx, (source_id, _, vrems_election) in enumerate(election_data):
            if is_referendum(vrems_election):
                logger.debug("sc_vrems.skip_referendum election_id=%s name=%s", source_id, vrems_election.get("electionName"))
                skipped_count += 1
                continue

            if not is_filing_open(vrems_election):
                logger.debug("sc_vrems.filing_not_open election_id=%s filing_opens=%s",
                             source_id, vrems_election.get("filingPeriodBeginDate"))
                skipped_count += 1
                continue

            election_obj = elections_by_source_id.get(source_id)
            if not election_obj:
                logger.warning("sc_vrems.sync_elections.missing_pk source_id=%s", source_id)
                continue

            # Stagger subtasks at 2-second intervals to avoid HTTP burst against VREMS.
            sync_sc_races.apply_async(
                args=[election_obj.pk, vrems_election["electionId"]],
                countdown=queued_count * 2,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count,
                "skipped": skipped_count, "queued": queued_count}

    except SCVremsRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("sc_vrems.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sc_races(self, election_pk: int, vrems_election_id: str | int):
    """
    Stage 2: Fetch candidates from VREMS for one election and upsert Race + Candidate records.

    Groups candidates into races using office + filing location + counties + party
    (party partitioning is applied for primary elections so R/D primaries stay separate).
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("sc_vrems.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="sc_vrems",
        task_name="sync_sc_races",
        status=SyncLog.Status.STARTED,
    )
    client = VremsClient()
    created_count = updated_count = 0

    try:
        candidates = client.get_candidates(vrems_election_id)
        logger.info("sc_vrems.sync_races election=%s candidates=%d",
                    election_obj.source_id, len(candidates))

        if not candidates:
            logger.info("sc_vrems.sync_races.empty_table election=%s — filing may not be open yet",
                        election_obj.source_id)
            sync_log.notes = "No candidates returned — filing period may not be open yet"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0}

        # Build a lightweight election dict for grouping logic (only name is needed)
        vrems_election_stub = {"electionName": election_obj.name}
        race_groups = build_race_groups(vrems_election_stub, candidates)

        now = timezone.now()

        # --- Bulk upsert Races ---
        race_objects: list[Race] = []
        group_candidates_map: list[tuple[str, list]] = []
        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            canonical_key = race_defaults.pop("canonical_key")
            if not canonical_key:
                logger.warning("sc_vrems.sync_races.null_canonical_key election=%s office=%s",
                               election_obj.source_id, race_defaults.get("office_title"))
                continue
            race_objects.append(Race(
                canonical_key=canonical_key,
                election=election_obj,
                last_synced_at=now,
                **race_defaults,
            ))
            group_candidates_map.append((canonical_key, group["candidates"]))

        canonical_keys = [r.canonical_key for r in race_objects]

        with transaction.atomic():
            # Pre-fetch existing canonical_keys for accounting (1 query).
            existing_race_keys = set(
                Race.objects.filter(canonical_key__in=canonical_keys)
                .values_list("canonical_key", flat=True)
            ) if canonical_keys else set()

            # Bulk upsert all races (1 query).
            Race.objects.bulk_create(
                race_objects,
                update_conflicts=True,
                update_fields=[
                    "election", "race_type", "office_title", "jurisdiction",
                    "geography_scope", "certification_status", "source",
                    "race_status", "vote_method", "max_selections",
                    "ocd_division_id", "normalized_office_title",
                    "source_metadata", "last_synced_at",
                ],
                unique_fields=["canonical_key"],
            )
            race_created = sum(1 for r in race_objects if r.canonical_key not in existing_race_keys)
            race_updated = len(race_objects) - race_created

            # Fetch back with PKs for candidate assignment (1 query).
            races_by_key: dict[str, Race] = {
                r.canonical_key: r
                for r in Race.objects.filter(canonical_key__in=canonical_keys).only("id", "canonical_key")
            } if canonical_keys else {}

            # --- Bulk upsert Candidates ---
            # Build candidate list, deduplicating by (race_id, name) so ON CONFLICT
            # is never asked to update the same target row twice in one statement.
            seen_cand_keys: set[tuple[int, str]] = set()
            candidate_objects: list[Candidate] = []
            for canonical_key, vrems_candidates in group_candidates_map:
                race = races_by_key.get(canonical_key)
                if not race:
                    continue
                for vc in vrems_candidates:
                    name = (vc.get("name_on_ballot") or "").strip()
                    if not name:
                        continue
                    cand_key = (race.id, name)
                    if cand_key in seen_cand_keys:
                        continue
                    seen_cand_keys.add(cand_key)
                    candidate_objects.append(Candidate(race=race, name=name, **map_candidate(vc)))

            if candidate_objects:
                # Pre-fetch existing (race_id, name) pairs for accounting (1 query).
                existing_cand_keys = set(
                    Candidate.objects.filter(race__in=list(races_by_key.values()))
                    .values_list("race_id", "name")
                )
                cand_created = sum(
                    1 for c in candidate_objects if (c.race.id, c.name) not in existing_cand_keys
                )
                cand_updated = len(candidate_objects) - cand_created

                # Bulk upsert all candidates (1 query).
                Candidate.objects.bulk_create(
                    candidate_objects,
                    update_conflicts=True,
                    update_fields=["party", "incumbent", "candidate_status", "source_metadata"],
                    unique_fields=["race", "name"],
                )
            else:
                cand_created = cand_updated = 0

        created_count = race_created + cand_created
        updated_count = race_updated + cand_updated

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count}

    except SCVremsRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("sc_vrems.sync_races.failed election=%s", election_obj.source_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
