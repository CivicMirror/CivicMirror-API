from __future__ import annotations

from datetime import date

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import MiSosClient
from .exceptions import MiSosRetryableError
from .mappers import candidate_status, normalize_office_title, party_abbrev
from .parsers import parse_boe_candidate_listing

_MI_ELECTION_SPECS = [
    {
        "name": "2026 Michigan Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 8, 4),
        "boe_type": "PRI",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_primary",
    },
    {
        "name": "2026 Michigan General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "boe_type": "GEN",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_general",
    },
]


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_mi_elections(self=None):
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="mi_sos",
        task_name="sync_mi_elections",
        status=SyncLog.Status.STARTED,
    )
    created = updated = 0
    client = MiSosClient()

    try:
        for spec in _MI_ELECTION_SPECS:
            election, _ = ingest.ingest_election(
                source="mi_sos",
                source_id=spec["source_id"],
                identity={
                    "state": "MI",
                    "election_type": spec["election_type"],
                    "election_date": spec["election_date"],
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": spec["name"],
                    "status": (
                        Election.Status.UPCOMING
                        if spec["election_date"] > timezone.localdate()
                        else Election.Status.RESULTS_PENDING
                    ),
                    "source_metadata": {
                        "mi_boe_election_type": spec["boe_type"],
                        "mi_boe_election_year": spec["boe_year"],
                    },
                },
            )

            rows = parse_boe_candidate_listing(
                client.fetch_candidate_listing(spec["boe_type"], spec["boe_year"])
            )
            seen: set[int] = set()
            for row in rows:
                office_title = normalize_office_title(row["office_title"])
                race, race_created = ingest.ingest_race(
                    election=election,
                    source="mi_sos",
                    identity={
                        "office_title": office_title,
                        "ocd_division_id": "",
                        "race_type": Race.RaceType.CANDIDATE,
                    },
                    fields={
                        "jurisdiction": "Michigan",
                        "source_metadata": {"mi_office_raw": row["office_title"]},
                    },
                )
                created += int(race_created)

                cand, cand_created = ingest.ingest_candidate(
                    race=race,
                    source="mi_sos",
                    name=row["candidate_name"],
                    party=party_abbrev(row["party"]),
                    fields={
                        "candidate_status": candidate_status(row["status"]),
                        "source_metadata": {
                            "mi_candidate_status_raw": row["status"],
                            "mi_filing_method": row["filing_method"],
                            "mi_candidate_address": row["candidate_address"],
                            "mi_filed_on": row["filed_on"],
                            "mi_incumbent_raw": row["incumbent"],
                        },
                    },
                )
                seen.add(cand.pk)
                created += int(cand_created)
                updated += int(not cand_created)

            Candidate.objects.filter(
                race__election=election,
                race__source="mi_sos",
                candidate_status=Candidate.CandidateStatus.RUNNING,
            ).exclude(pk__in=seen).update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

            election.last_synced_at = timezone.now()
            election.save(update_fields=["last_synced_at"])

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"created": created, "updated": updated}
    except MiSosRetryableError as exc:
        if self is None:
            raise
        raise self.retry(exc=exc)
    except Exception as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
