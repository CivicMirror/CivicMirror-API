"""
Massachusetts SOS Celery tasks.

Stage 1 — sync_ma_elections:
  Discover election and ballot question IDs from electionstats HTML search pages.
  Fetch OCPF schedule for election dates.
  Upsert Election records via bulk_create(update_conflicts=True).
  Queue sync_ma_races for each election and sync_ma_ballot_question for each BQ.

Stage 2 — sync_ma_races:
  Download CSV for one election from electionstats.
  Parse candidate column headers + party row.
  Upsert Race + Candidate records.

Stage 3 — sync_ma_ballot_question:
  Fetch BQ view page, parse inline JS election_data object.
  Download BQ CSV, parse Yes/No totals.
  Upsert Race + MeasureOption records.

Trigger endpoint: POST /internal/tasks/sync-ma-sos/
"""
import logging
from datetime import date

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, MeasureOption, Race
from ops.models import SyncLog

from . import parsers
from .client import MaSosClient
from .exceptions import MaSosError, MaSosRetryableError
from .mappers import map_ballot_question, map_candidate, map_election, map_race

logger = logging.getLogger(__name__)

# Stage values searched each sync run
_SYNC_STAGES = ["General", "Primaries"]

# Tally columns that are NOT real candidates
_TALLY_LABELS = parsers.TALLY_LABELS


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_elections(self):
    """
    Stage 1: Discover MA elections and ballot questions and upsert Election records.

    Searches the current year and prior year for General and Primaries stages.
    Queues sync_ma_races for each election and sync_ma_ballot_question for each BQ.
    """
    sync_log = SyncLog.objects.create(
        source="ma_sos",
        task_name="sync_ma_elections",
        status=SyncLog.Status.STARTED,
    )
    client = MaSosClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        today = date.today()
        current_year = today.year

        # Fetch OCPF schedules for election dates
        schedule_current = client.get_ocpf_schedule(current_year)
        schedule_prior = client.get_ocpf_schedule(current_year - 1)

        # Discover all election IDs for both years
        all_election_rows: list[dict] = []
        for year in (current_year, current_year - 1):
            schedule = schedule_current if year == current_year else schedule_prior
            for stage in _SYNC_STAGES:
                rows = client.get_election_ids(year, stage)
                for row in rows:
                    row["_schedule"] = schedule
                all_election_rows.extend(rows)

        # Deduplicate by election_id
        seen_ids: set[int] = set()
        unique_rows: list[dict] = []
        for row in all_election_rows:
            eid = row["election_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                unique_rows.append(row)

        logger.info("ma_sos.sync_elections.discovered count=%d", len(unique_rows))

        if not unique_rows:
            sync_log.notes = "No elections discovered from electionstats"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "queued": 0}

        # Build mapped election dicts, skipping any without a resolvable election_date
        election_data: list[tuple[str, dict]] = []
        for row in unique_rows:
            schedule = row.pop("_schedule", {})
            mapped = map_election(row, schedule)
            source_id = mapped.pop("source_id")
            defaults = {**mapped, "last_synced_at": timezone.now()}
            if defaults.get("election_date") is None:
                logger.warning("ma_sos.sync_elections.skipped_no_date source_id=%s", source_id)
                continue
            election_data.append((source_id, defaults))

        source_ids = [d[0] for d in election_data]

        existing_source_ids = set(
            Election.objects.filter(source_id__in=source_ids).values_list("source_id", flat=True)
        ) if source_ids else set()

        election_objects = [
            Election(source_id=sid, **defaults)
            for sid, defaults in election_data
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

        created_count = sum(1 for sid, _ in election_data if sid not in existing_source_ids)
        updated_count = len(election_data) - created_count

        # Reload to get PKs for task dispatch
        elections_by_source_id = {
            e.source_id: e
            for e in Election.objects.filter(source_id__in=source_ids)
        } if source_ids else {}

        for idx, (source_id, defaults) in enumerate(election_data):
            election_obj = elections_by_source_id.get(source_id)
            if not election_obj:
                logger.warning("ma_sos.sync_elections.missing_pk source_id=%s", source_id)
                skipped_count += 1
                continue
            electionstats_id = (election_obj.source_metadata or {}).get("electionstats_id")
            if not electionstats_id:
                skipped_count += 1
                continue
            sync_ma_races.apply_async(
                args=[election_obj.pk],
                countdown=idx * 3,
            )
            queued_count += 1

        # Discover and queue ballot questions for current year
        bq_ids = client.get_ballot_question_ids(current_year)
        bq_base_countdown = len(unique_rows) * 3
        for bq_idx, bq_id in enumerate(bq_ids):
            sync_ma_ballot_question.apply_async(
                args=[bq_id],
                countdown=bq_base_countdown + bq_idx * 3,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = (
            f"Queued {queued_count - len(bq_ids)} race syncs + {len(bq_ids)} BQ syncs; "
            f"{skipped_count} skipped"
        )
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

    except MaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ma_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_races(self, election_pk: int):
    """
    Stage 2: Download election CSV, parse candidates, and upsert Race + Candidate records.

    Looks up the election by PK, builds the CSV URL from source_metadata["electionstats_id"],
    parses candidate column headers and party row, then bulk-upserts.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("ma_sos.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="ma_sos",
        task_name="sync_ma_races",
        status=SyncLog.Status.STARTED,
    )
    client = MaSosClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        electionstats_id = (election_obj.source_metadata or {}).get("electionstats_id")
        if not electionstats_id:
            sync_log.notes = "No electionstats_id in election.source_metadata"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return

        csv_bytes = client.download_election_csv(electionstats_id, precincts=False)
        candidate_rows = parsers.parse_election_csv(csv_bytes)

        # Filter out synthetic tally labels
        real_candidates = [c for c in candidate_rows if c["name"] not in _TALLY_LABELS]

        if not real_candidates and not candidate_rows:
            sync_log.notes = "Empty CSV — no candidates found"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return

        # Build the race row from the election's stored metadata
        election_row = {
            "election_id": electionstats_id,
            "office": election_obj.source_metadata.get("office", ""),
            "district": election_obj.source_metadata.get("district", ""),
            "stage": election_obj.source_metadata.get("stage", "General"),
        }

        # Infer office/district from election name if not in metadata
        if not election_row["office"] and election_obj.name:
            # e.g. "2024 MA U.S. House 1st Congressional General" → extract office
            parts = election_obj.name.split(" ")
            if len(parts) >= 3:
                election_row["office"] = " ".join(parts[2:4]) if len(parts) > 4 else parts[2]

        race_fields = map_race(election_obj, election_row)
        canonical_key = race_fields.pop("canonical_key")

        now = timezone.now()

        with transaction.atomic():
            existing_race_keys = set(
                Race.objects.filter(canonical_key=canonical_key).values_list("canonical_key", flat=True)
            )

            Race.objects.bulk_create(
                [Race(canonical_key=canonical_key, election=election_obj, last_synced_at=now, **race_fields)],
                update_conflicts=True,
                update_fields=[
                    "election", "race_type", "office_title", "normalized_office_title",
                    "jurisdiction", "geography_scope", "certification_status", "source",
                    "race_status", "vote_method", "max_selections", "ocd_division_id",
                    "source_metadata", "last_synced_at",
                ],
                unique_fields=["canonical_key"],
            )
            race_created = 1 if canonical_key not in existing_race_keys else 0
            race_updated = 0 if race_created else 1

            race_obj = Race.objects.get(canonical_key=canonical_key)

            candidate_objects = [
                Candidate(race=race_obj, name=c["name"], **map_candidate(c))
                for c in real_candidates
            ]

            if candidate_objects:
                existing_cand_keys = set(
                    Candidate.objects.filter(race=race_obj).values_list("name", flat=True)
                )
                cand_created = sum(1 for c in candidate_objects if c.name not in existing_cand_keys)
                cand_updated = len(candidate_objects) - cand_created
                Candidate.objects.bulk_create(
                    candidate_objects,
                    update_conflicts=True,
                    update_fields=["party", "candidate_status", "source_metadata"],
                    unique_fields=["race", "name"],
                )

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

    except MaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "ma_sos.sync_races.failed election=%s",
            getattr(election_obj, "source_id", "?"),
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_ballot_question(self, bq_id: int):
    """
    Stage 3: Fetch BQ metadata + CSV and upsert Race + MeasureOption records.

    Fetches the BQ view page to extract inline JS metadata, downloads the BQ CSV
    for Yes/No totals, then upserts the Race and Yes/No MeasureOption records.
    """
    sync_log = SyncLog.objects.create(
        source="ma_sos",
        task_name="sync_ma_ballot_question",
        status=SyncLog.Status.STARTED,
    )
    client = MaSosClient()

    try:
        metadata = client.get_ballot_question_metadata(bq_id)
        if not metadata:
            sync_log.notes = f"No metadata found for bq_id={bq_id}"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return

        # Resolve or create the associated Election record
        bq_date_str = metadata.get("date", "")
        election_obj = _get_or_create_bq_election(bq_date_str, metadata.get("year", 0))
        if not election_obj:
            sync_log.notes = f"Could not resolve election for bq_id={bq_id} date={bq_date_str}"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return

        race_fields = map_ballot_question(metadata, election_obj)
        canonical_key = race_fields.pop("canonical_key")
        now = timezone.now()

        with transaction.atomic():
            existing_keys = set(
                Race.objects.filter(canonical_key=canonical_key).values_list("canonical_key", flat=True)
            )
            Race.objects.bulk_create(
                [Race(canonical_key=canonical_key, election=election_obj, last_synced_at=now, **race_fields)],
                update_conflicts=True,
                update_fields=[
                    "election", "race_type", "office_title", "normalized_office_title",
                    "jurisdiction", "geography_scope", "certification_status", "source",
                    "race_status", "vote_method", "max_selections", "ocd_division_id",
                    "source_metadata", "last_synced_at",
                ],
                unique_fields=["canonical_key"],
            )
            race_created = 1 if canonical_key not in existing_keys else 0

            race_obj = Race.objects.get(canonical_key=canonical_key)
            MeasureOption.objects.get_or_create(race=race_obj, label="Yes")
            MeasureOption.objects.get_or_create(race=race_obj, label="No")

        sync_log.records_created = race_created
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "status", "completed_at"])

        return {"race_created": bool(race_created), "bq_id": bq_id}

    except MaSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ma_sos.sync_ballot_question.failed bq_id=%d", bq_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_bq_election(date_str: str, year: int) -> Election | None:
    """
    Resolve an existing MA general Election for ballot questions, or create a stub.

    Ballot questions always belong to the general election for their date/year.
    Tries to match an existing election by date; creates a stub if none found.
    """
    from datetime import datetime

    from .mappers import infer_election_status

    if date_str:
        try:
            election_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            election_date = None
    else:
        election_date = None

    if not election_date and year:
        # Fall back to a generic "general election year" source_id stub
        source_id = f"ma_sos_general_{year}"
    elif election_date:
        source_id = f"ma_sos_general_{election_date.isoformat()}"
    else:
        logger.error("ma_sos._get_or_create_bq_election: no date or year")
        return None

    # Try to find an existing election with this date
    if election_date:
        existing = Election.objects.filter(
            state="MA",
            election_type="general",
            election_date=election_date,
        ).first()
        if existing:
            return existing

    # Create a stub general election
    status = infer_election_status(election_date)
    stub, _ = Election.objects.get_or_create(
        source_id=source_id,
        defaults={
            "name": f"{year or (election_date.year if election_date else '')} MA General Election",
            "election_date": election_date,
            "election_type": "general",
            "jurisdiction_level": Election.JurisdictionLevel.STATE,
            "state": "MA",
            "status": status,
            "source_metadata": {"stub": True, "created_by": "sync_ma_ballot_question"},
        },
    )
    return stub
