from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election, MeasureOption
from ops.models import SyncLog

from .client import CURRENT_ELECTION_URL, ELECTION_DATES_URL, OPEN_OFFICES_GENERAL_URL, OrSosClient
from .mappers import map_candidate, map_election, map_measure_race, map_race, map_race_from_candidate_filing
from .parsers import (
    ballot_return_payload,
    latest_ballot_returns_by_election,
    parse_ballot_count_history,
    parse_candidate_filings,
    parse_election_page,
    parse_local_measures,
    parse_open_offices_pdf,
)

logger = logging.getLogger(__name__)

_SOURCE = "or_sos"
_DEFAULT_2026_GENERAL_ID = "1453"
_DEFAULT_2026_PRIMARY_ID = "1451"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_or_candidates(self, election_pk: int, election_id: str = _DEFAULT_2026_GENERAL_ID, election_year: int = 2026):
    """Sync Oregon ORESTAR candidate filings for one election."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("or_sos.sync_candidates.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_or_candidates",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        client = OrSosClient()
        race_created = race_updated = cand_created = cand_updated = 0
        parsed_total = 0
        seen_pages: set[tuple[tuple[str, str, str], ...]] = set()
        seen_filings: set[tuple[str, str, str, str]] = set()
        for page_index in range(20):
            html, _ = client.search_candidate_filings(election_year, election_id, page_index)
            filings = parse_candidate_filings(html)
            if not filings:
                break
            page_signature = tuple((filing.ballot_name, filing.office, filing.party) for filing in filings)
            if page_signature in seen_pages:
                logger.warning("or_sos.sync_candidates.duplicate_page page=%d", page_index)
                break
            seen_pages.add(page_signature)
            for filing in filings:
                filing_key = (filing.ballot_name, filing.office, filing.party, filing.election)
                if filing_key in seen_filings:
                    continue
                seen_filings.add(filing_key)
                parsed_total += 1
                race_fields = map_race_from_candidate_filing(election_obj, filing)
                race_fields.pop("source", None)
                race_identity = {
                    "office_title": race_fields.pop("office_title"),
                    "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                    "race_type": race_fields.pop("race_type"),
                }
                race_obj, race_was_new = ingest.ingest_race(
                    election=election_obj,
                    source=_SOURCE,
                    identity=race_identity,
                    fields=race_fields,
                )
                if race_was_new:
                    race_created += 1
                else:
                    race_updated += 1

                cand_fields = map_candidate(filing)
                party = cand_fields.pop("party", "")
                _, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source=_SOURCE,
                    name=filing.ballot_name,
                    party=party,
                    fields=cand_fields,
                )
                if cand_was_new:
                    cand_created += 1
                else:
                    cand_updated += 1

            if len(filings) < 50:
                break

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.notes = f"filings={parsed_total} races_created={race_created} candidates_created={cand_created}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "notes", "status", "completed_at"])
        return {
            "filings": parsed_total,
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except Exception as exc:
        logger.exception("or_sos.sync_candidates.failed election=%s", election_pk)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_or_local_measures(self, election_pk: int, election_id: str = _DEFAULT_2026_PRIMARY_ID, election_year: int = 2026):
    """Sync Oregon ORESTAR local measures for one election."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("or_sos.sync_local_measures.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_or_local_measures",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        client = OrSosClient()
        created = updated = parsed_total = 0
        seen_pages: set[tuple[str, ...]] = set()
        seen_measures: set[tuple[str, str, str]] = set()
        for page_index in range(20):
            html, _ = client.search_local_measures(election_year, election_id, page_index)
            measures = parse_local_measures(html)
            if not measures:
                break
            page_signature = tuple(measure.measure_number for measure in measures)
            if page_signature in seen_pages:
                logger.warning("or_sos.sync_local_measures.duplicate_page page=%d", page_index)
                break
            seen_pages.add(page_signature)
            for measure in measures:
                measure_key = (measure.measure_number, measure.election, measure.county)
                if measure_key in seen_measures:
                    continue
                seen_measures.add(measure_key)
                parsed_total += 1
                race_fields = map_measure_race(election_obj, measure)
                race_fields.pop("source", None)
                race_identity = {
                    "office_title": race_fields.pop("office_title"),
                    "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                    "race_type": race_fields.pop("race_type"),
                }
                race_obj, was_created = ingest.ingest_race(
                    election=election_obj,
                    source=_SOURCE,
                    identity=race_identity,
                    fields=race_fields,
                )
                MeasureOption.objects.get_or_create(race=race_obj, option_label="Yes")
                MeasureOption.objects.get_or_create(race=race_obj, option_label="No")
                if was_created:
                    created += 1
                else:
                    updated += 1
            if len(measures) < 50:
                break

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"local_measures={parsed_total}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "notes", "status", "completed_at"])
        return {"measures": parsed_total, "created": created, "updated": updated}

    except Exception as exc:
        logger.exception("or_sos.sync_local_measures.failed election=%s", election_pk)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_or_turnout(self):
    """Sync Oregon ballot-return summaries from the public Socrata dataset."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_or_turnout",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = OrSosClient()
        raw_rows, source_url = client.fetch_ballot_count_history()
        records = parse_ballot_count_history(raw_rows)
        latest_by_date = latest_ballot_returns_by_election(records)
        elections = Election.objects.filter(state="OR", election_date__in=list(latest_by_date.keys()))

        updated = 0
        for election in elections:
            record = latest_by_date.get(election.election_date)
            if not record:
                continue
            metadata = dict(election.source_metadata or {})
            metadata["or_sos_ballot_return"] = ballot_return_payload(record, source_url)
            election.source_metadata = metadata
            election.save(update_fields=["source_metadata"])
            updated += 1

        sync_log.records_updated = updated
        sync_log.notes = f"rows={len(raw_rows)} parsed={len(records)} latest_elections={len(latest_by_date)}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_updated", "notes", "status", "completed_at"])
        return {"updated": updated, "parsed": len(records), "latest_elections": len(latest_by_date)}

    except Exception as exc:
        logger.exception("or_sos.sync_turnout.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_or_elections(self):
    """Seed Oregon elections from SOS current-election and election-dates pages."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_or_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        client = OrSosClient()
        election_infos = []
        for url in (CURRENT_ELECTION_URL, ELECTION_DATES_URL):
            html, resolved_url = client.fetch_page_text(url)
            election_infos.extend(parse_election_page(html, source_url=resolved_url))

        created = updated = skipped = queued = 0
        seen: set[tuple[str, str]] = set()
        for info in election_infos:
            mapped = map_election(info)
            dedupe_key = (mapped["election_date"].isoformat(), mapped["election_type"])
            if dedupe_key in seen:
                skipped += 1
                continue
            seen.add(dedupe_key)

            source_id = mapped.pop("source_id")
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created += 1
            else:
                updated += 1

            orestar_election_id = (fields.get("source_metadata") or {}).get("or_sos_orestar_election_id") or ""
            if identity["election_type"] == Election.ElectionType.GENERAL:
                sync_or_race_skeleton.apply_async(args=[election_obj.pk], countdown=queued * 5)
                queued += 1
                if orestar_election_id:
                    sync_or_candidates.apply_async(
                        args=[election_obj.pk, orestar_election_id, identity["election_date"].year],
                        countdown=queued * 5,
                    )
                    queued += 1
            elif identity["election_type"] == Election.ElectionType.PRIMARY and orestar_election_id:
                sync_or_local_measures.apply_async(
                    args=[election_obj.pk, orestar_election_id, identity["election_date"].year],
                    countdown=queued * 5,
                )
                queued += 1

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.records_skipped = skipped
        sync_log.notes = f"elections_discovered={len(election_infos)} race_skeleton_queued={queued}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "skipped": skipped, "queued": queued}

    except Exception as exc:
        logger.exception("or_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_or_race_skeleton(self, election_pk: int, source_url: str = OPEN_OFFICES_GENERAL_URL):
    """Create/update Oregon core federal and state race skeletons from the SOS Open Offices PDF."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("or_sos.sync_race_skeleton.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_or_race_skeleton",
        status=SyncLog.Status.STARTED,
    )

    try:
        from aggregation import ingest

        client = OrSosClient()
        content, resolved_url = client.fetch_open_offices_pdf(source_url)
        offices = parse_open_offices_pdf(content)

        created = updated = skipped = 0
        for office in offices:
            race_fields = map_race(election_obj, office, resolved_url)
            race_fields.pop("source", None)
            identity = {
                "office_title": race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type": race_fields.pop("race_type"),
            }
            if not identity["office_title"]:
                skipped += 1
                continue

            _, was_created = ingest.ingest_race(
                election=election_obj,
                source=_SOURCE,
                identity=identity,
                fields=race_fields,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.records_skipped = skipped
        sync_log.notes = f"open_offices={len(offices)} source_url={resolved_url}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "skipped": skipped}

    except Exception as exc:
        logger.exception("or_sos.sync_race_skeleton.failed election=%s", election_pk)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
