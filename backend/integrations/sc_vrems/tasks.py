import logging
from datetime import date as _date

from celery import shared_task
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

        for idx, vrems_election in enumerate(elections):
            mapped = map_election(vrems_election)
            source_id = mapped.pop("source_id")

            election_obj, created = Election.objects.update_or_create(
                source_id=source_id,
                defaults={**mapped, "last_synced_at": timezone.now()},
            )
            created_count += int(created)
            updated_count += int(not created)

            if is_referendum(vrems_election):
                logger.debug("sc_vrems.skip_referendum election_id=%s name=%s", source_id, vrems_election.get("electionName"))
                skipped_count += 1
                continue

            if not is_filing_open(vrems_election):
                logger.debug("sc_vrems.filing_not_open election_id=%s filing_opens=%s",
                             source_id, vrems_election.get("filingPeriodBeginDate"))
                skipped_count += 1
                continue

            # Stagger subtasks at 2-second intervals to avoid HTTP burst against VREMS.
            sync_sc_races.apply_async(
                args=[election_obj.pk, vrems_election["electionId"]],
                countdown=idx * 2,
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

        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            canonical_key = race_defaults.pop("canonical_key")

            race, race_created = Race.objects.update_or_create(
                canonical_key=canonical_key,
                defaults={"election": election_obj, **race_defaults, "last_synced_at": timezone.now()},
            )
            created_count += int(race_created)
            updated_count += int(not race_created)

            for vrems_candidate in group["candidates"]:
                name = (vrems_candidate.get("name_on_ballot") or "").strip()
                if not name:
                    continue
                _, cand_created = Candidate.objects.update_or_create(
                    race=race,
                    name=name,
                    defaults=map_candidate(vrems_candidate),
                )
                created_count += int(cand_created)
                updated_count += int(not cand_created)

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
