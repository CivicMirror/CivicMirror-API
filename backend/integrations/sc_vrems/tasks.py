import logging
from datetime import date as _date

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import VremsClient
from .exceptions import SCVremsRetryableError
from .mappers import (
    build_race_groups,
    is_filing_open,
    is_referendum,
    map_candidate,
    map_election,
    map_race,
)

logger = logging.getLogger(__name__)

# Limit to current and next calendar year by default.
# Pass years=[...] explicitly to sync_sc_elections for historical backfill.
_DEFAULT_YEARS = None  # resolved dynamically at task runtime — see sync_sc_elections


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sc_elections(self, years: list[int] | None = None):
    """
    Stage 1: Fetch all SC elections from VREMS and upsert via the aggregation
    ingest service. Queues sync_sc_races for elections where filing is open.
    """
    sync_log = SyncLog.objects.create(
        source="sc_vrems",
        task_name="sync_sc_elections",
        status=SyncLog.Status.STARTED,
    )
    client = VremsClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        elections = client.get_all_elections(
            years=years or [_date.today().year, _date.today().year + 1]
        )
        logger.info("sc_vrems.sync_elections found=%d", len(elections))

        from aggregation import ingest

        election_objects: list[tuple[object, dict]] = []  # (election_obj, vrems_election)

        for vrems_election in elections:
            mapped = map_election(vrems_election)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}

            election_obj, was_created = ingest.ingest_election(
                source="sc_vrems",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1
            election_objects.append((election_obj, vrems_election))

        for election_obj, vrems_election in election_objects:
            if is_referendum(vrems_election):
                logger.debug(
                    "sc_vrems.skip_referendum election_id=%s name=%s",
                    vrems_election.get("electionId"),
                    vrems_election.get("electionName"),
                )
                skipped_count += 1
                continue

            if not is_filing_open(vrems_election):
                logger.debug(
                    "sc_vrems.filing_not_open election_id=%s filing_opens=%s",
                    vrems_election.get("electionId"),
                    vrems_election.get("filingPeriodBeginDate"),
                )
                skipped_count += 1
                continue

            sync_sc_races.apply_async(
                args=[election_obj.pk, vrems_election["electionId"]],
                countdown=queued_count * 2,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs"
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

    except SCVremsRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("sc_vrems.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_sc_races(self, election_pk: int, vrems_election_id: str | int):
    """
    Stage 2: Fetch candidates from VREMS for one election and upsert Race + Candidate
    records via the aggregation ingest service.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("sc_vrems.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="sc_vrems",
        task_name="sync_sc_races",
        status=SyncLog.Status.STARTED,
    )
    client = VremsClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        candidates = client.get_candidates(vrems_election_id)
        logger.info(
            "sc_vrems.sync_races election=%s candidates=%d",
            election_obj.source_id or election_obj.pk,
            len(candidates),
        )

        if not candidates:
            logger.info(
                "sc_vrems.sync_races.empty_table election=%s — filing may not be open yet",
                election_obj.source_id or election_obj.pk,
            )
            sync_log.notes = "No candidates returned — filing period may not be open yet"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0}

        vrems_election_stub = {"electionName": election_obj.name}
        race_groups = build_race_groups(vrems_election_stub, candidates)

        from aggregation import ingest

        seen_race_pks: set[int] = set()
        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            # Discard the legacy source-scoped canonical_key — ingest builds its own.
            race_defaults.pop("canonical_key", None)
            # Ingest sets Race.source from contributing_sources precedence.
            race_defaults.pop("source", None)

            race_identity = {
                "office_title":    race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type":       race_defaults.pop("race_type"),
            }
            if not race_identity["office_title"]:
                logger.warning(
                    "sc_vrems.sync_races.null_canonical_key election=%s office=%s",
                    election_obj.source_id or election_obj.pk,
                    race_defaults.get("normalized_office_title"),
                )
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source="sc_vrems",
                identity=race_identity,
                fields=race_defaults,
            )
            if race_obj.pk not in seen_race_pks:
                seen_race_pks.add(race_obj.pk)
                if race_was_new:
                    race_created += 1
                else:
                    race_updated += 1

            seen_names: set[str] = set()
            for vc in group["candidates"]:
                name = (vc.get("name_on_ballot") or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                cand_fields = map_candidate(vc)
                party = cand_fields.pop("party", "")
                _, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source="sc_vrems",
                    name=name,
                    party=party,
                    fields=cand_fields,
                )
                if cand_was_new:
                    cand_created += 1
                else:
                    cand_updated += 1

        created_count = race_created + cand_created
        updated_count = race_updated + cand_updated

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

    except SCVremsRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "sc_vrems.sync_races.failed election=%s",
            getattr(election_obj, "source_id", None) or getattr(election_obj, "pk", "?"),
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
