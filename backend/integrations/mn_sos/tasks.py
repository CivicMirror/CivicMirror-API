"""
Minnesota SOS Celery tasks.

sync_mn_races (single Stage 1 task, no-arg) iterates every election in the
registry (data/elections.toml) and, for each:
  1. Upsert the Election row from its descriptor.
  2. Probe the file host (by date path) for the in-scope result files.
  3. Parse each in-scope result file to collect the in-scope (office_id,
     office_name) set — the office-level scope filter, since cand.txt itself
     mixes federal/state/county candidates together.
  4. Fetch + parse cand.txt, filter to in-scope office_ids, upsert Race +
     Candidate rows via the aggregation ingest service.
  5. Mark any previously-RUNNING candidate for this election not seen this
     run as WITHDRAWN (MN's own documented candidate lifecycle).

Each election is synced independently: one election's failure is recorded and
skipped, it does not abort the others.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate
from ops.models import SyncLog

from .client import MnSosClient
from .discovery import probe_in_scope_files
from .election_registry import load_elections
from .exceptions import MnSosError, MnSosRetryableError
from .mappers import format_office_title, map_candidate, map_election, map_race
from .parsers import parse_candidate_table, parse_result_file

logger = logging.getLogger(__name__)


def _sync_one_election(client, election) -> dict:
    """Sync races + candidates for one registered election; return counts."""
    from aggregation import ingest

    created_count = updated_count = withdrawn_count = 0

    mapped_election = map_election(election)
    source_id = mapped_election.pop("source_id")
    identity = {
        "state": mapped_election["state"],
        "election_type": mapped_election["election_type"],
        "election_date": mapped_election["election_date"],
        "jurisdiction_level": mapped_election["jurisdiction_level"],
    }
    fields = {k: v for k, v in mapped_election.items() if k not in identity}
    election_obj, _ = ingest.ingest_election(
        source="mn_sos", source_id=source_id, identity=identity, fields=fields,
    )

    meta = election_obj.source_metadata or {}
    date_path = meta.get("mn_date_path")
    if not date_path:
        raise MnSosError(f"MN election {source_id} is missing mn_date_path metadata")

    in_scope_files = probe_in_scope_files(client, date_path)

    in_scope_office_ids: set[str] = set()
    office_titles_by_id: dict[str, str] = {}
    district_by_id: dict[str, str] = {}
    fetch_failure_count = 0
    for file_entry in in_scope_files:
        try:
            text = client.fetch_file(file_entry["url"])
        except Exception as exc:
            logger.warning(
                "mn_sos.sync_races.result_file_fetch_failed url=%s err=%s",
                file_entry["url"], exc,
            )
            fetch_failure_count += 1
            continue
        for row in parse_result_file(text):
            in_scope_office_ids.add(row["office_id"])
            office_titles_by_id.setdefault(row["office_id"], row["office_name"])
            district_by_id.setdefault(row["office_id"], row["district"])

    if not in_scope_office_ids:
        logger.info(
            "mn_sos.sync_races.no_in_scope_offices source_id=%s date_path=%s",
            source_id, date_path,
        )
        return {"created": 0, "updated": 0, "withdrawn": 0}

    cand_text = client.fetch_candidate_table(date_path)
    candidate_rows = [
        row for row in parse_candidate_table(cand_text)
        if row["office_id"] in in_scope_office_ids
    ]

    seen_candidate_pks: set[int] = set()

    for office_id in in_scope_office_ids:
        office_title = format_office_title(
            office_titles_by_id[office_id],
            district_by_id.get(office_id, ""),
        )
        race_defaults = map_race(office_id, office_title)
        race_identity = {
            "office_title": race_defaults.pop("office_title"),
            "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
            "race_type": race_defaults.pop("race_type"),
        }
        race_defaults.pop("source", None)

        race_obj, race_was_new = ingest.ingest_race(
            election=election_obj, source="mn_sos",
            identity=race_identity, fields=race_defaults,
        )
        if race_was_new:
            created_count += 1
        else:
            updated_count += 1

        for row in candidate_rows:
            if row["office_id"] != office_id:
                continue
            name = row["candidate_name"].strip()
            if not name:
                continue
            cand_fields = map_candidate(row)
            party = cand_fields.pop("party", "")
            cand_obj, cand_was_new = ingest.ingest_candidate(
                race=race_obj, source="mn_sos", name=name, party=party, fields=cand_fields,
            )
            seen_candidate_pks.add(cand_obj.pk)
            if cand_was_new:
                created_count += 1
            else:
                updated_count += 1

    if fetch_failure_count == 0:
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj, race__source="mn_sos")
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
    else:
        logger.warning(
            "mn_sos.sync_races.skipping_withdrawal_check_due_to_fetch_failures "
            "source_id=%s fetch_failure_count=%s",
            source_id, fetch_failure_count,
        )

    election_obj.last_synced_at = timezone.now()
    election_obj.save(update_fields=["last_synced_at"])

    return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_mn_races(self):
    sync_log = SyncLog.objects.create(
        source="mn_sos",
        task_name="sync_mn_races",
        status=SyncLog.Status.STARTED,
    )
    client = MnSosClient()
    totals = {"created": 0, "updated": 0, "withdrawn": 0}
    errors: list[str] = []
    retryable_exc: MnSosRetryableError | None = None

    elections = load_elections()
    for election in elections:
        try:
            counts = _sync_one_election(client, election)
        except MnSosRetryableError as exc:
            retryable_exc = exc
            errors.append(f"{election.source_id}: {exc}")
            logger.warning(
                "mn_sos.sync_races.retryable source_id=%s err=%s", election.source_id, exc,
            )
            continue
        except Exception as exc:
            errors.append(f"{election.source_id}: {exc}")
            logger.exception("mn_sos.sync_races.election_failed source_id=%s", election.source_id)
            continue
        for key in totals:
            totals[key] += counts[key]

    synced_ok = len(elections) - len(errors)
    sync_log.records_created = totals["created"]
    sync_log.records_updated = totals["updated"]
    sync_log.notes = f"elections={len(elections)} ok={synced_ok} withdrawn={totals['withdrawn']}"
    sync_log.completed_at = timezone.now()
    update_fields = ["records_created", "records_updated", "notes", "completed_at", "status"]
    if errors:
        sync_log.error_count = len(errors)
        sync_log.last_error = "; ".join(errors)
        update_fields += ["error_count", "last_error"]
        # Partial progress -> warnings; nothing synced at all -> failed.
        if totals["created"] or totals["updated"]:
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        else:
            sync_log.status = SyncLog.Status.FAILED
    else:
        sync_log.status = SyncLog.Status.COMPLETED
    sync_log.save(update_fields=update_fields)

    if retryable_exc is not None:
        raise self.retry(exc=retryable_exc)

    return {"created": totals["created"], "updated": totals["updated"], "withdrawn": totals["withdrawn"]}
