from __future__ import annotations

import logging
from collections import defaultdict

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import HawaiiOlvrClient
from .mappers import map_candidate_fields, map_election, map_race_fields
from .parsers import parse_candidate_report_csv

logger = logging.getLogger(__name__)

_SOURCE = "hi_olvr"
_PRIMARY_STATUS = "In Primary"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_hi_elections(self=None):
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_hi_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = HawaiiOlvrClient()
        _landing_html, report_url, elid = client.resolve_candidate_report()
        csv_bytes = client.fetch_candidate_report_csv(report_url)
        rows = [row for row in parse_candidate_report_csv(csv_bytes) if row.status == _PRIMARY_STATUS]

        election_fields = map_election()
        election, election_created = ingest.ingest_election(
            source=_SOURCE,
            source_id=election_fields.pop("source_id"),
            identity={
                "state": election_fields["state"],
                "election_type": election_fields["election_type"],
                "election_date": election_fields["election_date"],
                "jurisdiction_level": election_fields["jurisdiction_level"],
            },
            fields={
                "name": election_fields["name"],
                "status": (
                    election_fields["status"]
                    if election_fields["election_date"] > timezone.localdate()
                    else Election.Status.RESULTS_PENDING
                ),
                "source_metadata": {
                    "hi_olvr_landing_url": "https://elections.hawaii.gov/candidates/candidate-reports/",
                    "hi_olvr_report_url": report_url,
                    "hi_olvr_elid": elid,
                },
            },
        )

        created = int(election_created)
        updated = int(not election_created)
        seen_candidate_pks: set[int] = set()
        grouped: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            grouped[(row.contest, row.party)].append(row)

        for group_rows in grouped.values():
            row = group_rows[0]
            race_fields = map_race_fields(row, report_url, elid)
            contest_variant = race_fields.pop("contest_variant")
            race, race_created = ingest.ingest_race(
                election=election,
                source=_SOURCE,
                identity={
                    "office_title": race_fields.pop("office_title"),
                    "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                    "race_type": race_fields.pop("race_type"),
                    "contest_variant": contest_variant,
                },
                fields=race_fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for filing in group_rows:
                candidate_fields = map_candidate_fields(filing, report_url, elid)
                party = candidate_fields.pop("party", "")
                candidate, candidate_created = ingest.ingest_candidate(
                    race=race,
                    source=_SOURCE,
                    name=filing.ballot_name,
                    party=party,
                    fields=candidate_fields,
                )
                seen_candidate_pks.add(candidate.pk)
                created += int(candidate_created)
                updated += int(not candidate_created)

        withdrawn = Candidate.objects.filter(
            race__election=election,
            race__source=_SOURCE,
            candidate_status=Candidate.CandidateStatus.RUNNING,
        ).exclude(pk__in=seen_candidate_pks).update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

        election.last_synced_at = timezone.now()
        election.save(update_fields=["last_synced_at"])

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"rows={len(rows)} races={len(grouped)} withdrawn={withdrawn}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "notes", "status", "completed_at"])

        return {
            "rows": len(rows),
            "created": created,
            "updated": updated,
            "withdrawn": withdrawn,
        }

    except Exception as exc:
        logger.exception("hi_olvr.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
