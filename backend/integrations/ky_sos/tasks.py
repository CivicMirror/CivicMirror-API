"""
Kentucky SOS Candidate Filings Celery task.

Stage 1 — sync_ky_sos:
  Fetch the Candidate Filings directory page (gets both the current election
  label and the office-group directory in one request). Derive the Election
  record from the statutory general-election date formula + that label. Sweep
  the four in-scope office-group pages (US Senator, US Representative, State
  Senator, State Representative) plus the Withdrawn/Deceased/Disqualified
  group, upserting Race + Candidate rows for each.

See docs/superpowers/plans/2026-07-14-ky-sos-adapter.md for why this is a
single task rather than split election/candidate tasks like il_sbe, and why
there's no separate "Upcoming Election Summary" client call.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate
from ops.models import SyncLog

from .client import KentuckySosClient
from .exceptions import KySosRetryableError
from .mappers import IN_SCOPE_OFFICE_IDS, OFFICE_LABELS, map_candidate, map_election, map_race
from .parsers import parse_candidate_rows, parse_current_election, parse_office_directory

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ky_sos(self):
    sync_log = SyncLog.objects.create(
        source="ky_sos",
        task_name="sync_ky_sos",
        status=SyncLog.Status.STARTED,
    )
    client = KentuckySosClient()
    created_count = updated_count = 0

    try:
        from aggregation import ingest

        directory_html = client.fetch_directory()
        current_election = parse_current_election(directory_html)
        offices = parse_office_directory(directory_html)

        mapped_election = map_election(current_election["label"])
        source_id = mapped_election.pop("source_id")
        identity = {
            "state": mapped_election["state"],
            "election_type": mapped_election["election_type"],
            "election_date": mapped_election["election_date"],
            "jurisdiction_level": mapped_election["jurisdiction_level"],
        }
        fields = {k: v for k, v in mapped_election.items() if k not in identity}
        election_obj, _ = ingest.ingest_election(
            source="ky_sos", source_id=source_id, identity=identity, fields=fields,
        )

        for office in offices:
            if office["office_id"] not in IN_SCOPE_OFFICE_IDS:
                continue

            office_html = client.fetch_office(office["office_id"])
            rows = parse_candidate_rows(office_html)

            for row in rows:
                race_defaults = map_race(row["office"], row["district"])
                race_identity = {
                    "office_title": race_defaults.pop("office_title"),
                    "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                    "race_type": race_defaults.pop("race_type"),
                }
                race_defaults.pop("source", None)
                race_obj, race_created = ingest.ingest_race(
                    election=election_obj, source="ky_sos",
                    identity=race_identity, fields=race_defaults,
                )
                created_count += int(race_created)
                updated_count += int(not race_created)

                name, party, cand_fields = map_candidate(row, Candidate.CandidateStatus.RUNNING)
                _, cand_created = ingest.ingest_candidate(
                    race=race_obj, source="ky_sos", name=name, party=party, fields=cand_fields,
                )
                created_count += int(cand_created)
                updated_count += int(not cand_created)

        withdrawn_html = client.fetch_withdrawn()
        in_scope_office_labels = set(OFFICE_LABELS.values())
        for row in parse_candidate_rows(withdrawn_html):
            if row["office"] not in in_scope_office_labels:
                continue

            race_defaults = map_race(row["office"], row["district"])
            race_identity = {
                "office_title": race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type": race_defaults.pop("race_type"),
            }
            race_defaults.pop("source", None)
            race_obj, race_created = ingest.ingest_race(
                election=election_obj, source="ky_sos",
                identity=race_identity, fields=race_defaults,
            )
            created_count += int(race_created)
            updated_count += int(not race_created)

            name, party, cand_fields = map_candidate(row, Candidate.CandidateStatus.WITHDRAWN)
            _, cand_created = ingest.ingest_candidate(
                race=race_obj, source="ky_sos", name=name, party=party, fields=cand_fields,
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

    except KySosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ky_sos.sync_ky_sos.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
