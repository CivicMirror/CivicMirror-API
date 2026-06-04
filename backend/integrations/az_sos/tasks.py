"""
AZ SOS Celery tasks.

sync_az_elections (Stage 1a):
    Always seeds Election records first (cheap; rows must exist).
    Fetches CandidateList HTML and fingerprints it.
    If unchanged → skips candidate parsing (log "candidate parsing skipped").
    If changed → upserts Race + Candidate records for FEDERAL + STATE branches.
    Deduplicates candidates by az_candidate_id (stable external key), not name.
    Marks candidates absent from this run as WITHDRAWN.
    Enqueues sync_az_candidate_details.

sync_az_candidate_details (Stage 1b):
    Fetches CandidateDetail at 1 req/sec for candidates that have az_candidate_id
    but lack az_bio in source_metadata (new candidates only; does not re-fetch).
"""
from __future__ import annotations

import hashlib
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import AzSosClient
from .exceptions import AzSosRetryableError
from .mappers import AZ_ELECTIONS, geography_scope, normalize_candidate_name, normalize_contest_name, party_abbrev
from .parsers import parse_candidate_detail, parse_candidate_list

logger = logging.getLogger(__name__)

_FINGERPRINT_CACHE_KEY = "az_sos:candidate_list_fingerprint"
_FINGERPRINT_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days


def _seed_elections() -> dict[str, Election]:
    """Upsert Election records from AZ_ELECTIONS. Runs every invocation."""
    from aggregation import ingest
    elections: dict[str, Election] = {}
    for spec in AZ_ELECTIONS:
        election, _ = ingest.ingest_election(
            source="az_sos",
            source_id=spec["source_id"],
            identity={
                "state": "AZ",
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
            },
        )
        elections[spec["election_type"]] = election
    return elections


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_az_elections(self):
    """Stage 1a: seed elections + upsert races/candidates from CandidateList."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="az_sos",
        task_name="sync_az_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        # Elections always seeded, regardless of fingerprint.
        elections = _seed_elections()
        primary = elections["primary"]

        client = AzSosClient()
        html_bytes = client.fetch_candidate_list()
        fingerprint = hashlib.md5(html_bytes).hexdigest()

        if cache.get(_FINGERPRINT_CACHE_KEY) == fingerprint:
            logger.info("az_sos.sync_elections.candidate_parsing_skipped fingerprint=%s", fingerprint)
            sync_log.notes = "CandidateList unchanged; candidate parsing skipped"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created_candidates": 0, "skipped": True}

        entries = parse_candidate_list(html_bytes)
        logger.info("az_sos.sync_elections.parsed entries=%d", len(entries))

        created_races = created_cands = updated_cands = 0
        seen_candidate_pks: set[int] = set()

        for entry in entries:
            canonical_name = normalize_contest_name(entry.race_name)

            race, race_created = ingest.ingest_race(
                election=primary,
                source="az_sos",
                identity={
                    "office_title": canonical_name,
                    "ocd_division_id": "",
                    "race_type": "candidate",
                },
                fields={
                    "office_title": canonical_name,
                    "jurisdiction": "Arizona",
                    "geography_scope": geography_scope(entry.branch),
                    "source_metadata": {"az_branch": entry.branch},
                },
            )
            if race_created:
                created_races += 1

            # Dedup by stable az_candidate_id, not (name, party).
            existing = Candidate.objects.filter(
                race=race,
                source_metadata__az_candidate_id=entry.candidate_id,
            ).first()

            if existing:
                seen_candidate_pks.add(existing.pk)
                updated_cands += 1
            else:
                cand, _ = ingest.ingest_candidate(
                    race=race,
                    source="az_sos",
                    name=entry.name,
                    party=party_abbrev(entry.party),
                    fields={
                        "source_metadata": {
                            "az_candidate_id": entry.candidate_id,
                            "az_is_write_in": entry.is_write_in,
                            "az_party_full": entry.party,
                        },
                    },
                )
                seen_candidate_pks.add(cand.pk)
                created_cands += 1

        withdrawn = (
            Candidate.objects
            .filter(
                race__election=primary,
                race__source_metadata__has_key="az_branch",
                candidate_status=Candidate.CandidateStatus.RUNNING,
            )
            .exclude(pk__in=seen_candidate_pks)
            .update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
        )
        if withdrawn:
            logger.info("az_sos.sync_elections.withdrawn count=%d", withdrawn)

        cache.set(_FINGERPRINT_CACHE_KEY, fingerprint, _FINGERPRINT_CACHE_TTL)
        primary.last_synced_at = timezone.now()
        primary.save(update_fields=["last_synced_at"])

        sync_az_candidate_details.delay(primary.pk)

        sync_log.records_created = created_cands
        sync_log.notes = f"races_created={created_races} withdrawn={withdrawn}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])

        return {
            "created_races": created_races,
            "created_candidates": created_cands,
            "updated_candidates": updated_cands,
            "withdrawn": withdrawn,
        }

    except AzSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("az_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def sync_az_candidate_details(self, election_pk: int):
    """
    Stage 1b: enrich new candidates with bio/website/social.
    Only processes candidates that have az_candidate_id but lack az_bio —
    i.e., newly added since the last detail sweep.
    """
    try:
        election = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("az_sos.sync_candidate_details.missing_election pk=%d", election_pk)
        return

    candidates_needing_detail = (
        Candidate.objects
        .filter(
            race__election=election,
            race__source_metadata__has_key="az_branch",
            source_metadata__has_key="az_candidate_id",
        )
        .exclude(source_metadata__has_key="az_bio")
    )

    total = candidates_needing_detail.count()
    if not total:
        logger.info("az_sos.sync_candidate_details.nothing_to_do election=%d", election_pk)
        return

    logger.info("az_sos.sync_candidate_details.start election=%d count=%d", election_pk, total)
    client = AzSosClient()
    enriched = errors = 0

    for candidate in candidates_needing_detail.iterator():
        az_id = (candidate.source_metadata or {}).get("az_candidate_id")
        if not az_id:
            continue
        try:
            html_bytes = client.fetch_candidate_detail(int(az_id))
            detail = parse_candidate_detail(html_bytes)
        except AzSosRetryableError as exc:
            logger.warning("az_sos.sync_candidate_details.fetch_failed id=%s: %s", az_id, exc)
            errors += 1
            continue

        meta = dict(candidate.source_metadata or {})
        meta.update({
            "az_bio": detail.bio,
            "az_campaign_statement": detail.campaign_statement,
            "az_website": detail.website_url,
            "az_donation_url": detail.donation_url,
            "az_facebook": detail.facebook,
            "az_twitter": detail.twitter,
            "az_youtube": detail.youtube,
            "az_instagram": detail.instagram,
            "az_funding_type": detail.funding_type,
            "az_photo_url": detail.photo_url,
        })
        Candidate.objects.filter(pk=candidate.pk).update(source_metadata=meta)
        enriched += 1

    logger.info(
        "az_sos.sync_candidate_details.done election=%d enriched=%d errors=%d",
        election_pk, enriched, errors,
    )
