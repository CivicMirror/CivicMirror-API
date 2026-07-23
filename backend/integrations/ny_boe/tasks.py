from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import NyBoeClient
from .mappers import map_candidate, map_contest_to_race
from .parsers import parse_certification_pdf, validate_certification_snapshot

logger = logging.getLogger(__name__)

_SOURCE = "ny_boe"


def merge_source_metadata(existing: dict | None, updates: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_source_metadata(merged[key], value)
        else:
            merged[key] = value
    return merged


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ny_elections(self):
    from aggregation import ingest

    sync_log = SyncLog.objects.create(source=_SOURCE, task_name="sync_ny_elections", status=SyncLog.Status.STARTED)
    client = NyBoeClient()
    created = updated = queued = 0
    try:
        documents = client.get_current_certification_documents()
        for document in documents:
            source_id = f"ny_boe_{document['election_type']}_{document['election_date'].isoformat()}"
            existing = Election.objects.filter(
                state="NY",
                election_type=document["election_type"],
                election_date=document["election_date"],
                jurisdiction_level=Election.JurisdictionLevel.STATE,
            ).first()
            metadata = merge_source_metadata(
                existing.source_metadata if existing else {},
                {
                    "ny_boe": {
                        "document_type": document["document_type"],
                        "title": document["title"],
                        "landing_url": document["landing_url"],
                        "pdf_url": document["pdf_url"],
                    }
                },
            )
            election, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity={
                    "state": "NY",
                    "election_type": document["election_type"],
                    "election_date": document["election_date"],
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": document["title"],
                    "status": (
                        Election.Status.UPCOMING
                        if document["election_date"] > timezone.localdate()
                        else Election.Status.RESULTS_PENDING
                    ),
                    "source_metadata": metadata,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
            sync_ny_races.delay(election.pk)
            queued += 1
        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"queued={queued}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "notes", "status", "completed_at"])
        return {"created": created, "updated": updated, "queued": queued}
    except Exception as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ny_races(self, election_pk: int):
    from aggregation import ingest

    try:
        election = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("ny_boe.sync_races.missing_election pk=%d", election_pk)
        return
    sync_log = SyncLog.objects.create(election=election, source=_SOURCE, task_name="sync_ny_races", status=SyncLog.Status.STARTED)
    try:
        pdf_url = ((election.source_metadata or {}).get("ny_boe") or {}).get("pdf_url")
        if not pdf_url:
            raise ValueError("Election.source_metadata.ny_boe.pdf_url is required")
        client = NyBoeClient()
        doc = parse_certification_pdf(client.fetch_certification_pdf(pdf_url))
        issues = validate_certification_snapshot(doc)
        if issues:
            sync_log.error_count = len(issues)
            sync_log.last_error = "; ".join(issues[:5])
            sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
            return {"created": 0, "updated": 0, "errors": len(issues)}

        created = updated = 0
        seen_race_pks = set()
        seen_candidate_pks = set()
        for contest in doc.get("contests") or []:
            existing_race = Race.objects.filter(
                election=election,
                source_metadata__source_key=contest.get("key", ""),
            ).first()
            identity, fields = map_contest_to_race(
                contest,
                election,
                existing_metadata=existing_race.source_metadata if existing_race else {},
            )
            race, race_created = ingest.ingest_race(election=election, source=_SOURCE, identity=identity, fields=fields)
            seen_race_pks.add(race.pk)
            created += int(race_created)
            updated += int(not race_created)
            for candidate_row in contest.get("candidates") or []:
                name = (candidate_row.get("name") or "").strip()
                if not name:
                    continue
                existing_candidate = race.candidates.filter(name=name).first()
                candidate, _ = ingest.ingest_candidate(
                    race=race,
                    source=_SOURCE,
                    name=name,
                    party=contest.get("party", ""),
                    fields=map_candidate(
                        candidate_row,
                        existing_metadata=existing_candidate.source_metadata if existing_candidate else {},
                    ),
                )
                seen_candidate_pks.add(candidate.pk)

        Race.objects.filter(election=election, source=Race.Source.NY_BOE).exclude(pk__in=seen_race_pks).update(
            race_status=Race.RaceStatus.ARCHIVED
        )
        Candidate.objects.filter(race__election=election, race__source=Race.Source.NY_BOE).exclude(
            pk__in=seen_candidate_pks
        ).update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"created": created, "updated": updated, "errors": 0}
    except Exception as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
