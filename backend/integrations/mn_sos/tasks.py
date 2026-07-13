"""
Minnesota SOS Celery tasks.

sync_mn_races (single Stage 1 task, no-arg):
  1. Upsert the hardcoded Nov 2024 general POC Election row.
  2. Fetch the file index, filter to Federal+State in-scope files.
  3. Parse each in-scope result file to collect the in-scope (office_id,
     office_name) set — this is the office-level scope filter, since
     cand.txt itself mixes federal/state/county candidates together.
  4. Fetch + parse cand.txt, filter to in-scope office_ids, upsert Race +
     Candidate rows via the aggregation ingest service.
  5. Mark any previously-RUNNING candidate for this election not seen this
     run as WITHDRAWN (MN's own documented candidate lifecycle — see
     docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate
from ops.models import SyncLog

from .client import MnSosClient
from .exceptions import MnSosRetryableError
from .mappers import is_in_scope_file, map_candidate, map_election, map_race
from .parsers import parse_candidate_table, parse_file_index, parse_result_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_mn_races(self):
    sync_log = SyncLog.objects.create(
        source="mn_sos",
        task_name="sync_mn_races",
        status=SyncLog.Status.STARTED,
    )
    client = MnSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        from aggregation import ingest

        mapped_election = map_election()
        source_id = mapped_election.pop("source_id")
        identity = {
            "state": mapped_election["state"],
            "election_type": mapped_election["election_type"],
            "election_date": mapped_election["election_date"],
            "jurisdiction_level": mapped_election["jurisdiction_level"],
        }
        fields = {k: v for k, v in mapped_election.items() if k not in identity}
        election_obj, election_was_created = ingest.ingest_election(
            source="mn_sos", source_id=source_id, identity=identity, fields=fields,
        )
        # ingest_election only records source_id on ElectionSourceLink for the
        # canonical-key path; MN is currently single-source, so mirror it onto
        # Election.source_id directly for convenient lookup (e.g. admin, tests).
        if election_obj.source_id != source_id:
            election_obj.source_id = source_id
            election_obj.save(update_fields=["source_id"])

        meta = election_obj.source_metadata or {}
        ers_election_id = meta.get("mn_ers_election_id")

        index_html = client.fetch_file_index(ers_election_id)
        all_files = parse_file_index(index_html)
        in_scope_files = [f for f in all_files if is_in_scope_file(f["label"])]

        in_scope_office_ids: set[str] = set()
        office_titles_by_id: dict[str, str] = {}
        for file_entry in in_scope_files:
            try:
                text = client.fetch_file(file_entry["url"])
            except Exception as exc:
                logger.warning(
                    "mn_sos.sync_races.result_file_fetch_failed url=%s err=%s",
                    file_entry["url"], exc,
                )
                continue
            for row in parse_result_file(text):
                in_scope_office_ids.add(row["office_id"])
                office_titles_by_id.setdefault(row["office_id"], row["office_name"])

        if not in_scope_office_ids:
            sync_log.notes = "No in-scope offices found in result files"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0}

        cand_url = f"https://electionresultsfiles.sos.mn.gov/{meta['mn_date_path']}/cand.txt"
        cand_text = client.fetch_file(cand_url)
        candidate_rows = [
            row for row in parse_candidate_table(cand_text)
            if row["office_id"] in in_scope_office_ids
        ]

        seen_candidate_pks: set[int] = set()

        for office_id in in_scope_office_ids:
            office_title = office_titles_by_id[office_id]
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

        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj, race__source="mn_sos")
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"withdrawn={withdrawn_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}

    except MnSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("mn_sos.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
