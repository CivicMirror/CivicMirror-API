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
from django.utils import timezone

from elections.models import Election, MeasureOption
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

        from aggregation import ingest

        election_objects: list[Election] = []
        for idx, row in enumerate(unique_rows):
            schedule = row.pop("_schedule", {})
            mapped = map_election(row, schedule)
            source_id = mapped.pop("source_id")
            if mapped.get("election_date") is None:
                logger.warning("ma_sos.sync_elections.skipped_no_date source_id=%s", source_id)
                skipped_count += 1
                continue
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            # Everything else (name, status, source_metadata, …) becomes ingest fields.
            fields = {k: v for k, v in mapped.items() if k not in identity}
            # Extract electionstats_id from fields before ingest — source_metadata may
            # not be written back to election_obj if a higher-precedence source already
            # owns the identity fields on an existing canonical election.
            electionstats_id = (fields.get("source_metadata") or {}).get("electionstats_id")
            if not electionstats_id:
                skipped_count += 1
                continue
            election_obj, was_created = ingest.ingest_election(
                source="ma_sos", source_id=source_id, identity=identity, fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            sync_ma_races.apply_async(
                args=[election_obj.pk, electionstats_id],
                countdown=idx * 3,
            )
            queued_count += 1
            election_objects.append(election_obj)

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
def sync_ma_races(self, election_pk: int, electionstats_id: int):
    """
    Stage 2: Download election CSV, parse candidates, and upsert Race + Candidate records.

    Looks up the election by PK, builds the CSV URL from the provided electionstats_id,
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

        # Build the race row from stored metadata; fall back to empty strings if
        # a higher-precedence source owns source_metadata on the canonical election.
        meta = election_obj.source_metadata or {}
        election_row = {
            "election_id": electionstats_id,
            "office": meta.get("office", ""),
            "district": meta.get("district", ""),
            "stage": meta.get("stage", "General"),
        }

        # Infer office/district from election name if not in metadata
        if not election_row["office"] and election_obj.name:
            # e.g. "2024 MA U.S. House 1st Congressional General" → extract office
            parts = election_obj.name.split(" ")
            if len(parts) >= 3:
                election_row["office"] = " ".join(parts[2:4]) if len(parts) > 4 else parts[2]

        from aggregation import ingest

        race_fields = map_race(election_obj, election_row)
        # The mapper's legacy `canonical_key` is source-scoped — discard it.
        # The ingest service builds its own source-independent canonical key.
        race_fields.pop("canonical_key", None)
        race_identity = {
            "office_title": race_fields.pop("office_title"),
            "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
            "race_type": race_fields.pop("race_type"),
        }
        race_obj, race_was_new = ingest.ingest_race(
            election=election_obj, source="ma_sos",
            identity=race_identity, fields=race_fields,
        )
        race_created = 1 if race_was_new else 0
        race_updated = 0 if race_was_new else 1

        for c in real_candidates:
            cand_fields = map_candidate(c)
            cand_name = c.get("name", "")
            cand_party = cand_fields.pop("party", "")
            if not cand_name:
                continue
            _cand_obj, cand_was_new = ingest.ingest_candidate(
                race=race_obj, source="ma_sos",
                name=cand_name, party=cand_party, fields=cand_fields,
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

        from aggregation import ingest

        race_fields = map_ballot_question(metadata, election_obj)
        # Discard the legacy source-scoped canonical_key from the mapper —
        # the ingest service builds its own source-independent one.
        race_fields.pop("canonical_key", None)
        race_identity = {
            "office_title": race_fields["office_title"],
            "ocd_division_id": race_fields.get("ocd_division_id", ""),
            "race_type": race_fields["race_type"],
        }
        ingest_fields = {k: v for k, v in race_fields.items()
                         if k not in {"office_title", "ocd_division_id", "race_type"}}
        race_obj, race_was_new = ingest.ingest_race(
            election=election_obj, source="ma_sos",
            identity=race_identity, fields=ingest_fields,
        )
        race_created = 1 if race_was_new else 0

        MeasureOption.objects.get_or_create(race=race_obj, option_label="Yes")
        MeasureOption.objects.get_or_create(race=race_obj, option_label="No")

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
