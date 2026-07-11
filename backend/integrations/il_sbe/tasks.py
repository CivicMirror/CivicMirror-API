"""
Illinois SBE Celery tasks.

Stage 1a — sync_il_elections:
  Parse the ddlElections dropdown for known election labels, upsert Election
  rows for the ones we can reliably date (general/primary/consolidated;
  specials are skipped — see mappers.infer_election_type_and_date), and
  queue sync_il_races for each.

Stage 1b — sync_il_races:
  Resolve the election's encrypted SBE `ID` token (cached on the Election
  row after first resolution), fetch the Federal/Statewide + Senate results
  category pages, filter to Federal + State offices, and upsert Race rows.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE, IllinoisSbeClient
from .exceptions import IlSbeRetryableError
from .mappers import is_federal_or_state_office, map_election, map_race
from .parsers import parse_category_offices, parse_election_id_token, parse_election_options

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_il_elections(self):
    """Stage 1a: seed IL Election records and queue Stage 1b for each."""
    sync_log = SyncLog.objects.create(
        source="il_sbe",
        task_name="sync_il_elections",
        status=SyncLog.Status.STARTED,
    )
    client = IllinoisSbeClient()
    created_count = updated_count = skipped_count = queued_count = 0

    try:
        html = client.fetch_search_page()
        options = parse_election_options(html)

        from aggregation import ingest

        for option in options:
            mapped = map_election(option["value"], option["label"])
            if mapped is None:
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source="il_sbe",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            sync_il_races.delay(election_obj.pk)
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"skipped={skipped_count} (undatable) | queued={queued_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "queued": queued_count}

    except IlSbeRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("il_sbe.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_il_races(self, election_pk: int):
    """
    Stage 1b: resolve the election's SBE ID token, fetch its results category
    pages, and upsert Race rows for Federal + State offices.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("il_sbe.sync_races.missing_election pk=%d", election_pk)
        return None

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="il_sbe",
        task_name="sync_il_races",
        status=SyncLog.Status.STARTED,
    )
    client = IllinoisSbeClient()
    created_count = updated_count = 0

    try:
        meta = election_obj.source_metadata or {}
        election_value = meta.get("il_sbe_election_value", "")
        id_token = meta.get("il_sbe_election_id_token")

        if not id_token:
            election_page_html = client.fetch_election_page(election_value)
            id_token = parse_election_id_token(election_page_html)
            if not id_token:
                logger.info(
                    "il_sbe.sync_races.no_results_page_yet election=%s",
                    election_obj.source_id,
                )
                sync_log.notes = "No results category page available yet"
                sync_log.status = SyncLog.Status.COMPLETED
                sync_log.completed_at = timezone.now()
                sync_log.save(update_fields=["notes", "status", "completed_at"])
                return {"created": 0, "updated": 0}
            meta["il_sbe_election_id_token"] = id_token
            election_obj.source_metadata = meta
            election_obj.save(update_fields=["source_metadata"])

        offices: list[dict] = []
        for office_type_token in (OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE):
            category_html = client.fetch_category_page(id_token, office_type_token)
            offices.extend(parse_category_offices(category_html))

        from aggregation import ingest

        for office in offices:
            office_name = office["office_name"]
            if not is_federal_or_state_office(office_name):
                continue

            race_defaults = map_race(election_obj, office_name)
            race_identity = {
                "office_title": race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type": race_defaults.pop("race_type"),
            }
            race_defaults.pop("source", None)

            race_obj, was_created = ingest.ingest_race(
                election=election_obj,
                source="il_sbe",
                identity=race_identity,
                fields=race_defaults,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

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

    except IlSbeRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "il_sbe.sync_races.failed election=%s",
            getattr(election_obj, "source_id", None) or election_pk,
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
