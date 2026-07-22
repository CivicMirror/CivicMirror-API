"""
Vermont SOS Celery tasks.

Stage 1 — sync_vt_elections:
  Fetch elections/elections.json, upsert Election records for
  isStateWideElection=True rows (Phase 1 scope — local elections deferred
  per docs/state-research/VT/VT-Creation-Pipeline-Review.md section 7.3,
  until Election canonical identity gains a locality component). Queue
  sync_vt_races for current/future/recently-past (not-yet-certified)
  elections.

Stage 2 — sync_vt_races(election_pk, election_guid):
  Fetch the election manifest, read each enabled core category (federal,
  statewide, senate, house, county), and upsert Race + Candidate records.
  Uses contest_variant (aggregation.identity.race_canonical_key) to keep
  same-office primary-party contests distinct — see
  aggregation/migrations/0012_seed_vt_sos_precedence.py and the
  contest_variant addition in aggregation/identity.py.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import VermontSosClient
from .exceptions import VtSosError, VtSosRetryableError
from .mappers import (
    CORE_CATEGORIES,
    build_election_source_id,
    iter_named_candidates,
    map_candidate,
    map_election_identity,
    map_race_identity,
)

logger = logging.getLogger(__name__)

_SOURCE = "vt_sos"
_MANIFEST_FINGERPRINT_CACHE_KEY = "vt_sos:manifest_fingerprint:{election_pk}"
_MANIFEST_FINGERPRINT_CACHE_TTL = 86400 * 30  # 30 days

# Election.status values whose races are worth re-syncing. Certified/archived
# elections are historical and won't change again.
_ACTIVE_STATUSES = {
    Election.Status.UPCOMING,
    Election.Status.ACTIVE,
    Election.Status.RESULTS_PENDING,
}

# House contests carry a district code/name; other categories are statewide.
_DISTRICT_CATEGORIES = {"house", "senate", "county"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_vt_elections(self):
    """Stage 1: seed Vermont statewide elections and queue race syncs."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_vt_elections",
        status=SyncLog.Status.STARTED,
    )
    client = VermontSosClient()
    created_count = updated_count = queued_count = 0

    try:
        elections_index = client.list_elections()
        statewide_rows = [row for row in elections_index if row.get("isStateWideElection")]

        for row in statewide_rows:
            identity, fields = map_election_identity(row)
            if not identity.get("election_date"):
                logger.warning(
                    "vt_sos.sync_elections.unparseable_date guid=%s", row.get("electionGuid")
                )
                continue

            election, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=build_election_source_id(row["electionGuid"]),
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            if election.status in _ACTIVE_STATUSES:
                sync_vt_races.delay(election.pk, row["electionGuid"])
                queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"queued_race_syncs={queued_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "notes", "status", "completed_at"])
        return {"created": created_count, "updated": updated_count, "queued": queued_count}

    except VtSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("vt_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


def _contest_district(category: str, contest: dict) -> tuple[str, str]:
    if category not in _DISTRICT_CATEGORIES:
        return "", ""
    return (contest.get("dc") or "").strip(), (contest.get("dn") or "").strip()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_vt_races(self, election_pk: int, election_guid: str):
    """Stage 2: upsert Race + Candidate records from the election manifest's
    enabled core categories (federal, statewide, senate, house, county)."""
    from aggregation import ingest

    try:
        election = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("vt_sos.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election,
        source=_SOURCE,
        task_name="sync_vt_races",
        status=SyncLog.Status.STARTED,
    )
    client = VermontSosClient()
    created_count = updated_count = withdrawn_count = error_count = 0
    seen_candidate_pks: set[int] = set()
    touched_race_pks: set[int] = set()

    try:
        manifest = client.get_election_manifest(election_guid)

        fingerprint_key = _MANIFEST_FINGERPRINT_CACHE_KEY.format(election_pk=election_pk)
        fingerprint = manifest.get("lastUpdatedDate", "")
        if fingerprint and cache.get(fingerprint_key) == fingerprint:
            sync_log.notes = "Manifest unchanged; races not refreshed"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0, "errors": 0, "unchanged": True}

        for category in CORE_CATEGORIES:
            category_meta = manifest.get(category) or {}
            if not category_meta.get("isEnable"):
                continue

            try:
                category_data = client.get_category(category_meta["path"])
            except VtSosError as exc:
                logger.warning(
                    "vt_sos.sync_races.category_error category=%s election=%d err=%s",
                    category, election_pk, exc,
                )
                error_count += 1
                continue

            for party_wrapper in category_data.get("d") or []:
                party_code = (party_wrapper.get("pc") or "").strip()
                party_name = (party_wrapper.get("pn") or "").strip()

                for contest in party_wrapper.get("o") or []:
                    district_code, district_name = _contest_district(category, contest)
                    identity, fields = map_race_identity(
                        category, contest, party_code, district_code, district_name,
                    )
                    race, race_created = ingest.ingest_race(
                        election=election, source=_SOURCE, identity=identity, fields=fields,
                    )
                    touched_race_pks.add(race.pk)
                    if race_created:
                        created_count += 1
                    else:
                        updated_count += 1

                    for raw_cand in iter_named_candidates(contest):
                        cand_name = (raw_cand.get("cn") or "").strip()
                        if not cand_name:
                            continue
                        cand_fields = map_candidate(raw_cand)
                        cand, _ = ingest.ingest_candidate(
                            race=race,
                            source=_SOURCE,
                            name=cand_name,
                            party=(raw_cand.get("pn") or party_name),
                            fields=cand_fields,
                        )
                        seen_candidate_pks.add(cand.pk)

        # Mark absent candidates WITHDRAWN, scoped to races actually touched
        # this run — a category the manifest disabled (e.g. town) must not
        # cause withdrawals for races outside this run's scope.
        withdrawn_qs = (
            Candidate.objects
            .filter(race__pk__in=touched_race_pks, source_metadata__has_key="candidate_id")
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
        if withdrawn_count:
            logger.info(
                "vt_sos.sync_races.withdrawn election=%d count=%d", election_pk, withdrawn_count,
            )

        election.last_synced_at = timezone.now()
        election.save(update_fields=["last_synced_at"])

        if fingerprint:
            cache.set(fingerprint_key, fingerprint, _MANIFEST_FINGERPRINT_CACHE_TTL)

        status = SyncLog.Status.COMPLETED if not error_count else SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.error_count = error_count
        sync_log.notes = f"withdrawn={withdrawn_count} errors={error_count}"
        sync_log.status = status
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "error_count", "notes", "status", "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "withdrawn": withdrawn_count,
            "errors": error_count,
        }

    except VtSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("vt_sos.sync_races.failed election=%d", election_pk)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
