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

Enrichment — sync_ocpf_ma_candidates:
  Fetch OCPF's legislative-race financial depository (one call/year) + full
  filer detail per candidate. Enriches Candidate records already created by
  sync_ma_races via CandidateMatcher — never creates candidates itself.

Trigger endpoint: POST /internal/tasks/sync-ma-sos/
                  POST /internal/tasks/sync-ocpf-ma/
"""
import logging
from datetime import date

from celery import shared_task
from django.utils import timezone

from elections.models import Election, MeasureOption
from integrations.orchestrator.candidate_matcher import CandidateMatcher
from integrations.orchestrator.exceptions import AmbiguousMatchError
from ops.models import SyncLog

from . import parsers
from .client import MaSosClient
from .exceptions import MaSosError, MaSosRetryableError
from .mappers import map_ballot_question, map_candidate, map_election, map_ocpf_filer, map_race

logger = logging.getLogger(__name__)

# Stage values searched each sync run. Party-specific stages are listed
# before the generic "Primaries" catch-all: electionstats returns the same
# election_id under both (e.g. election 171922 shows up for both
# stage:Republican and stage:Primaries), and discovery dedupes by
# election_id keeping the first-seen row — so querying the party-specific
# stage first is what lets the party label and per-party Race split (see
# mappers.contest_variant_key) survive into source_metadata. "Primaries"
# stays as a catch-all for primaries that aren't one of these parties (e.g.
# nonpartisan municipal primaries) — those keep today's merged-race behavior.
_SYNC_STAGES = [
    "General",
    "Democratic", "Republican", "Green-Rainbow", "Libertarian",
    "Working Families", "United Independent", "American", "Independent Voters",
    "Primaries",
]

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
                args=[
                    election_obj.pk, electionstats_id,
                    row.get("office", ""), row.get("district", ""), row.get("stage", "General"),
                ],
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
def sync_ma_races(
    self, election_pk: int, electionstats_id: int,
    office: str = "", district: str = "", stage: str = "",
):
    """
    Stage 2: Download election CSV, parse candidates, and upsert Race + Candidate records.

    Looks up the election by PK, builds the CSV URL from the provided electionstats_id,
    parses candidate column headers and party row, then bulk-upserts.

    office/district/stage come from the discovery row that queued this task
    (sync_ma_elections) and take precedence over election_obj.source_metadata:
    a partisan primary's Democratic and Republican contests share one
    *canonical* Election (see mappers.contest_variant_key), so its
    source_metadata.stage reflects whichever party synced last, not the
    party this specific electionstats_id belongs to. Falling back to
    source_metadata keeps old call sites (tests, manual triggers) working.
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

        # Prefer the discovery-row values passed in by sync_ma_elections (race-
        # scoped); fall back to the canonical election's stored metadata for
        # call sites that don't pass them (tests, manual triggers). See the
        # docstring above for why source_metadata alone isn't reliable once a
        # canonical election is shared across a primary's parties.
        meta = election_obj.source_metadata or {}
        election_row = {
            "election_id": electionstats_id,
            "office": office or meta.get("office", ""),
            "district": district or meta.get("district", ""),
            "stage": stage or meta.get("stage", "General"),
        }

        # Infer office/district from election name if still unknown
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
            "contest_variant": race_fields.pop("contest_variant", "") or "",
        }
        race_obj, race_was_new = ingest.ingest_race(
            election=election_obj, source="ma_sos",
            identity=race_identity, fields=race_fields,
        )
        race_created = 1 if race_was_new else 0
        race_updated = 0 if race_was_new else 1

        for c in real_candidates:
            cand_fields = map_candidate(c, stage=election_row["stage"])
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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ocpf_ma_candidates(self, year: int | None = None):
    """
    Enrichment: fetch OCPF's legislative-race financial depository for `year`
    (current year by default) plus full filer detail per candidate, and
    enrich already-ingested MA Candidate records via CandidateMatcher.

    Never creates candidates — sync_ma_races (the electionstats ballot CSV)
    is the source of truth for who's running; OCPF only fills gaps (legal
    name confirmation via matching, party, address, photo, ballot-status
    tags, and $ totals) on records that already exist.

    No SourceRecordStore checksum caching: candidate metadata/finances
    change often enough, and the candidate pool is small enough (~200 MA
    legislative seats), that re-matching every row every run is cheap and
    keeps the logic simple — CandidateMatcher.enrich() already no-ops
    cheaply ('skipped') when nothing has actually changed.
    """
    year = year or date.today().year
    sync_log = SyncLog.objects.create(
        source="ocpf",
        task_name="sync_ocpf_ma_candidates",
        status=SyncLog.Status.STARTED,
    )
    client = MaSosClient()
    matcher = CandidateMatcher()
    updated_count = skipped_count = warning_count = 0
    last_warning = ""

    try:
        depository_rows = client.get_legislative_depository(year)
        if not depository_rows:
            sync_log.notes = f"No OCPF legislative depository rows returned for {year}"
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"updated": 0, "skipped": 0, "warnings": 0}

        for row in depository_rows:
            cpf_id = row.get("cpfId")
            if not cpf_id:
                skipped_count += 1
                continue

            detail = client.get_filer_detail(cpf_id)
            payload = map_ocpf_filer(row, detail)
            if not payload.get("name"):
                skipped_count += 1
                continue

            try:
                candidate, action = matcher.enrich(
                    race=None, source="ocpf", external_id=str(cpf_id), enrichment_payload=payload,
                )
            except AmbiguousMatchError as exc:
                warning_count += 1
                last_warning = str(exc)
                skipped_count += 1
                continue

            if action == "enriched":
                updated_count += 1
                sources = list(candidate.contributing_sources or [])
                if "ocpf" not in sources:
                    sources.append("ocpf")
                    candidate.contributing_sources = sources
                    candidate.save(update_fields=["contributing_sources"])
            else:
                skipped_count += 1
                if action == "ambiguous":
                    warning_count += 1
                    last_warning = f"Ambiguous candidate match for ocpf:{cpf_id}"

        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.error_count = warning_count
        sync_log.last_error = last_warning
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS if warning_count else SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(
            update_fields=["records_updated", "records_skipped", "error_count", "last_error", "status", "completed_at"]
        )
        return {"updated": updated_count, "skipped": skipped_count, "warnings": warning_count}
    except Exception as exc:
        logger.exception("ocpf.sync_ma_candidates_failed year=%s", year)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
