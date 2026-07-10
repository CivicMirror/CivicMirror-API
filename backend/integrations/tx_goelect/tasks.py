"""
Texas GoElect Celery tasks.

Stage 1 — sync_tx_elections:
  Poll electionConstants for online elections; upsert Election records.
  Run sequential ID probe for undiscovered elections (e.g. November General).
  Queue sync_tx_races for each election.

Stage 2 — sync_tx_races:
  Fetch Lookups + OfficeSummary for one election.
  Upsert Race + Candidate records.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.utils import timezone

from elections.models import Election, MeasureOption, Race
from ops.models import SyncLog

from .client import TxGoElectClient
from .exceptions import TxGoElectError, TxGoElectRetryableError
from .mappers import map_candidate, map_election, map_race

logger = logging.getLogger(__name__)

_SOURCE = "tx_goelect"
_PROBE_WATERMARK_KEY = "tx_goelect:probe_watermark"
_PROBE_WATERMARK_INIT = 58315  # highest confirmed election ID as of 2026-06-17
_PROBE_MAX_MISSES = 50

# TX's largest statewide primaries run ~1300 offices / ~2000 candidates through
# sequential per-record ingest_race/ingest_candidate calls — measured at ~100s
# under uncontended conditions (2026-07-08), but consistently exceeded the
# previous 300s soft limit when sync_tx_elections queued a race sync while
# still mid-discovery itself (see the to_queue comment in sync_tx_elections).
# 600s/660s gives ~2x headroom over the uncontended baseline for any
# contention that queuing after discovery completes doesn't fully absorb.
_RACES_SOFT_TIME_LIMIT = 600
_RACES_TIME_LIMIT = 660


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tx_elections(self):
    """Stage 1: Discover TX elections and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_tx_elections",
        status=SyncLog.Status.STARTED,
    )
    client = TxGoElectClient()
    created_count = updated_count = skipped_count = 0
    # (election_pk, tx_election_id) pairs to queue as sync_tx_races once this
    # task is fully done — not queued inline during discovery. Queuing inline
    # let a race sync start executing while this task was still mid-loop
    # (more elections left to fetch/ingest, then the sequential ID probe),
    # and that overlap in DB/network activity is what pushed TX's largest
    # primaries past sync_tx_races's soft time limit every night.
    to_queue: list[tuple[int, int]] = []

    try:
        from aggregation import ingest

        # ── Poll electionConstants ──────────────────────────────────────────
        constants = client.get_election_constants()
        election_info = constants.get("electionInfo", {})

        for year, type_map in election_info.items():
            for type_code, elections in type_map.items():
                for election_id_str, meta in elections.items():
                    if meta.get("O") != "Y":
                        skipped_count += 1
                        continue

                    election_id = int(election_id_str)
                    election_name = meta.get("N", "")

                    try:
                        data = client.get_election_data(election_id)
                    except TxGoElectError as exc:
                        logger.warning(
                            "tx_goelect.sync_elections: data fetch failed id=%d: %s",
                            election_id, exc,
                        )
                        skipped_count += 1
                        continue

                    home = data.get("home") or {}
                    fields = map_election(election_id, type_code, home, election_name)
                    source_id = fields.pop("source_id")
                    identity = {
                        "state": fields["state"],
                        "election_type": fields["election_type"],
                        "election_date": fields["election_date"],
                        "jurisdiction_level": fields["jurisdiction_level"],
                    }

                    election_obj, was_created = ingest.ingest_election(
                        source=_SOURCE,
                        source_id=source_id,
                        identity=identity,
                        fields=fields,
                    )
                    if was_created:
                        created_count += 1
                    else:
                        updated_count += 1

                    to_queue.append((election_obj.pk, election_id))

        # ── Sequential ID probe ─────────────────────────────────────────────
        watermark = cache.get(_PROBE_WATERMARK_KEY, _PROBE_WATERMARK_INIT)
        misses = 0
        probe_id = watermark + 1

        while misses < _PROBE_MAX_MISSES:
            if not client.probe_election(probe_id):
                misses += 1
                probe_id += 1
                continue

            # Hit — reset miss counter; fetch full data and ingest
            misses = 0
            try:
                data = client.get_election_data(probe_id)
            except TxGoElectError as exc:
                logger.warning(
                    "tx_goelect.probe: data fetch failed id=%d: %s", probe_id, exc,
                )
                probe_id += 1
                continue

            home = data.get("home") or {}
            # Default to "S" — type code is unknown from probe alone.
            # Risk: if this election later appears in electionConstants as "GE",
            # ingest_election will create a second Election record (different canonical key).
            # The November General is expected to appear in electionConstants directly.
            # classify_election will set is_target_general_2026=True only when it
            # sees type_code=="GE" AND date==2026-11-03, so probed elections won't
            # produce false-positives; the real GE will show up in electionConstants
            # once it goes online.
            type_code = "S"
            election_name = f"Texas Election {probe_id}"

            fields = map_election(probe_id, type_code, home, election_name)
            source_id = fields.pop("source_id")
            identity = {
                "state": fields["state"],
                "election_type": fields["election_type"],
                "election_date": fields["election_date"],
                "jurisdiction_level": fields["jurisdiction_level"],
            }

            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            logger.info(
                "tx_goelect.probe: discovered election id=%d date=%s type=%s is_target=%s",
                probe_id,
                fields.get("election_date"),
                type_code,
                fields.get("source_metadata", {}).get("is_target_general_2026", False),
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            to_queue.append((election_obj.pk, probe_id))
            probe_id += 1

        cache.set(_PROBE_WATERMARK_KEY, probe_id - 1, timeout=None)

        # Only now — after every ingest_election call and the full probe scan
        # are done — start queuing race syncs, staggered 5s apart. This is
        # what actually keeps them from racing this task's own DB/network work
        # (a delay applied while discovery was still interleaved could not
        # guarantee that; discovery duration varies with how many elections
        # and probe misses there are).
        for idx, (election_pk, tx_election_id) in enumerate(to_queue):
            sync_tx_races.apply_async(
                args=[election_pk, tx_election_id],
                countdown=idx * 5,
            )

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {len(to_queue)} race syncs; probe watermark now {probe_id - 1}"
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
            "queued": len(to_queue),
        }

    except TxGoElectRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("tx_goelect.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(
    bind=True, max_retries=3, default_retry_delay=60,
    soft_time_limit=_RACES_SOFT_TIME_LIMIT, time_limit=_RACES_TIME_LIMIT,
)
def sync_tx_races(self, election_pk: int, tx_election_id: int):
    """Stage 2: Fetch Lookups + OfficeSummary; upsert Race + Candidate records."""
    logger.info("tx_goelect.sync_races.start election_pk=%d tx_id=%d", election_pk, tx_election_id)
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("tx_goelect.sync_races: election pk=%d not found", election_pk)
        return None

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_tx_races",
        status=SyncLog.Status.STARTED,
    )
    client = TxGoElectClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        from aggregation import ingest

        data = client.get_election_data(tx_election_id)
        lookups = data.get("lookups") or {}
        office_summary = data.get("office_summary") or {}

        offices = lookups.get("Office") or []
        office_type_map = {ot["ID"]: ot["OT"] for ot in (lookups.get("OfficeType") or [])}

        # Build per-office candidate lookup from OfficeSummary.
        # OfficeSummary.OS is a list of {OID, C: list|dict of candidates}.
        # Keyed by office ID so candidates are scoped to their own office.
        os_by_office_id: dict[int, list] = {
            entry["OID"]: (
                list(entry["C"].values())
                if isinstance(entry.get("C"), dict)
                else (entry.get("C") or [])
            )
            for entry in (office_summary.get("OS") or [])
        }

        for office in offices:
            office_type_id = office.get("OT")
            office_type_name = office_type_map.get(office_type_id, "")

            race_fields = map_race(election_obj, office, office_type_name, tx_election_id)
            race_fields.pop("source_id", None)
            race_identity = {
                "office_title": race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type": race_fields.pop("race_type"),
            }

            if not race_identity["office_title"]:
                logger.warning(
                    "tx_goelect.sync_races: null office title, skipping office_id=%s",
                    office.get("ID"),
                )
                continue

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

            if race_identity["race_type"] == Race.RaceType.MEASURE:
                MeasureOption.objects.get_or_create(race=race_obj, option_label="Yes")
                MeasureOption.objects.get_or_create(race=race_obj, option_label="No")
                continue

            # Seed candidates from OfficeSummary entries for this office only
            office_id = office["ID"]
            for cand_data in os_by_office_id.get(office_id) or []:
                cand_fields = map_candidate(tx_election_id, office_id, cand_data)
                name = cand_fields.pop("name", "")
                party = cand_fields.pop("party", "")
                if not name:
                    continue
                _, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source=_SOURCE,
                    name=name,
                    party=party,
                    fields=cand_fields,
                )
                if cand_was_new:
                    cand_created += 1
                else:
                    cand_updated += 1

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except SoftTimeLimitExceeded:
        logger.warning(
            "tx_goelect.sync_races.timeout election_pk=%d tx_id=%d exceeded %ds",
            election_pk, tx_election_id, _RACES_SOFT_TIME_LIMIT,
        )
        sync_log.error_count = 1
        sync_log.last_error = f"SoftTimeLimitExceeded ({_RACES_SOFT_TIME_LIMIT}s)"
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise

    except TxGoElectRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "tx_goelect.sync_races.failed election_pk=%d tx_id=%d",
            election_pk, tx_election_id,
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
