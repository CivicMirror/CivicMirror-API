"""
Ohio SOS CFDISCLOSURE Celery task.

Stage 1 — sync_oh_elections:
  Obtain CF bypass cookies via the CF solver service.
  Download ACT_CAN_LIST.CSV from Ohio CFDISCLOSURE (www6.ohiosos.gov).
  Parse the 764-row active candidate list.
  Upsert the Ohio General Election record.
  Upsert Race + Candidate records for all state legislative and statewide offices.
  Mark candidates absent from this run as WITHDRAWN.

The CSV contains:
  - 470 Ohio House of Representatives candidates (99 districts)
  - 105 Ohio State Senate candidates (33 districts on the ballot in 2026)
  - 87  Ohio Court of Appeals candidates
  - 19  Governor candidates
  - 14  Ohio Supreme Court Justice candidates
  - 14  State Board of Education candidates
  - and other statewide/judicial offices

Federal races (Ohio's 15 US House districts) are handled by Civic API.
"""
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import OhSosClient
from .exceptions import OhSosRetryableError
from .mappers import build_race_groups, map_candidate, map_election, map_race
from .parsers import parse_active_candidates

logger = logging.getLogger(__name__)


def _current_election_year() -> int:
    from django.utils import timezone as tz
    year = tz.localdate().year
    return year if year % 2 == 0 else year + 1


@shared_task(bind=True, max_retries=3, default_retry_delay=120, soft_time_limit=300, time_limit=360)
def sync_oh_elections(self):
    """
    Stage 1: Download and ingest the Ohio active candidate list from CFDISCLOSURE.
    """
    sync_log = SyncLog.objects.create(
        source="oh_sos",
        task_name="sync_oh_elections",
        status=SyncLog.Status.STARTED,
    )
    client = OhSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        from aggregation import ingest

        year = _current_election_year()

        # --- Ingest the election record ---
        mapped_election = map_election(year)
        source_id = mapped_election.pop("source_id")
        identity = {
            "state":              mapped_election["state"],
            "election_type":      mapped_election["election_type"],
            "election_date":      mapped_election["election_date"],
            "jurisdiction_level": mapped_election["jurisdiction_level"],
        }
        fields = {k: v for k, v in mapped_election.items() if k not in identity}
        election_obj, _ = ingest.ingest_election(
            source="oh_sos",
            source_id=source_id,
            identity=identity,
            fields=fields,
        )

        # --- Fetch and parse the CSV ---
        try:
            csv_text = client.fetch_active_candidates_csv()
        except OhSosRetryableError as exc:
            raise self.retry(exc=exc)

        candidates_raw = parse_active_candidates(csv_text)
        if not candidates_raw:
            logger.warning("oh_sos.sync_elections.empty_csv")
            sync_log.notes = "No candidates parsed from CSV"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0}

        race_groups = build_race_groups(candidates_raw)

        seen_candidate_pks: set[int] = set()

        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            race_defaults.pop("canonical_key", None)
            race_defaults.pop("source", None)

            race_identity = {
                "office_title":    race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type":       race_defaults.pop("race_type"),
            }
            if not race_identity["office_title"]:
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source="oh_sos",
                identity=race_identity,
                fields=race_defaults,
            )
            if race_was_new:
                created_count += 1
            else:
                updated_count += 1

            for raw_candidate in group["candidates"]:
                last  = raw_candidate.get("candidate_last_name", "").strip()
                first = raw_candidate.get("candidate_first_name", "").strip()
                if not last:
                    continue
                full_name = f"{first} {last}".strip() if first else last
                cand_fields = map_candidate(raw_candidate)
                party = cand_fields.pop("party", "")
                cand_obj, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source="oh_sos",
                    name=full_name,
                    party=party,
                    fields=cand_fields,
                )
                seen_candidate_pks.add(cand_obj.pk)
                if cand_was_new:
                    created_count += 1
                else:
                    updated_count += 1

        # Mark previously-active Ohio candidates no longer in the CSV as WITHDRAWN
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj)
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(
            candidate_status=Candidate.CandidateStatus.WITHDRAWN
        )
        if withdrawn_count:
            logger.info(
                "oh_sos.sync_elections.withdrawn election=%s count=%d",
                election_obj.source_id or election_obj.pk,
                withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = (
            f"candidates_parsed={len(candidates_raw)} "
            f"races={len(race_groups)} "
            f"withdrawn={withdrawn_count}"
        )
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "withdrawn": withdrawn_count,
        }

    except OhSosRetryableError:
        raise
    except SoftTimeLimitExceeded:
        logger.warning("oh_sos.sync_elections.timeout soft_limit=300s")
        sync_log.error_count = 1
        sync_log.last_error = "SoftTimeLimitExceeded after 300s"
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
    except Exception as exc:
        logger.exception("oh_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
