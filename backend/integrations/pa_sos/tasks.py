"""
PA SOS Celery tasks.

sync_pa_elections (Stage 1a):
    Seeds Election records for PA Primary and General.
    Fetches the candidate list JSON from ElectionInfo.aspx using PaSosClient.
    If the fingerprint of the JSON is unchanged → skips parsing for that election.
    If changed → upserts Race + Candidate records.
    Deduplicates candidates by pa_candidate_id (stable external key).
    Marks candidates absent from this run as WITHDRAWN.
    Enqueues sync_pa_candidate_details.

sync_pa_candidate_details (Stage 1b):
    Enriches candidates using detail page HTML from CandidateInfo.aspx.
    Uses a single browser session for batch processing to optimize performance.
"""
from __future__ import annotations

import hashlib
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import PaSosClient
from .exceptions import PaSosRetryableError
from .mappers import PA_ELECTIONS, geography_scope, party_abbrev, normalize_contest_name
from .parsers import parse_candidate_detail, parse_candidate_list

logger = logging.getLogger(__name__)

_FINGERPRINT_CACHE_KEY_PREFIX = "pa_sos:candidate_list_fingerprint:"
_FINGERPRINT_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days


def _seed_elections() -> dict[str, Election]:
    """Upsert PA Election records. Runs on every invocation."""
    from aggregation import ingest
    elections: dict[str, Election] = {}
    for spec in PA_ELECTIONS:
        election, _ = ingest.ingest_election(
            source="pa_sos",
            source_id=spec["source_id"],
            identity={
                "state": "PA",
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
def sync_pa_elections(self):
    """Stage 1a: seed elections + upsert races/candidates from Candidate list JSON."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="pa_sos",
        task_name="sync_pa_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        elections = _seed_elections()
        total_created = 0
        total_races = 0

        # We'll fetch candidate lists for both Primary and General elections
        with PaSosClient() as client:
            for spec in PA_ELECTIONS:
                etype = spec["election_type"]
                election = elections[etype]
                dropdown_val = spec["db_dropdown_value"]

                logger.info("Fetching candidate list for PA %s election (value %d)", etype, dropdown_val)
                json_str = client.fetch_candidate_list(dropdown_val)
                
                # Deduplicate/fingerprint check
                fingerprint = hashlib.md5(json_str.encode("utf-8")).hexdigest()
                cache_key = f"{_FINGERPRINT_CACHE_KEY_PREFIX}{etype}"
                
                if cache.get(cache_key) == fingerprint:
                    logger.info("pa_sos.sync_elections.skipped etype=%s fingerprint=%s", etype, fingerprint)
                    continue

                entries = parse_candidate_list(json_str)
                logger.info("pa_sos.sync_elections.parsed etype=%s entries=%d", etype, len(entries))

                seen_candidate_pks: set[int] = set()

                for entry in entries:
                    canonical_office = normalize_contest_name(entry.office, entry.district)

                    race, race_created = ingest.ingest_race(
                        election=election,
                        source="pa_sos",
                        identity={
                            "office_title": canonical_office,
                            "ocd_division_id": "",
                            "race_type": "candidate",
                        },
                        fields={
                            "office_title": canonical_office,
                            "jurisdiction": "Pennsylvania",
                            "geography_scope": geography_scope(canonical_office),
                            "source_metadata": {"pa_office_raw": entry.office, "pa_district_raw": entry.district},
                        },
                    )
                    if race_created:
                        total_races += 1

                    # Look up existing candidate by stable pa_candidate_id
                    existing = Candidate.objects.filter(
                        race=race,
                        source_metadata__pa_candidate_id=entry.candidate_id,
                    ).first()

                    if existing:
                        seen_candidate_pks.add(existing.pk)
                    else:
                        cand, _ = ingest.ingest_candidate(
                            race=race,
                            source="pa_sos",
                            name=entry.name,
                            party=party_abbrev(entry.party),
                            fields={
                                "source_metadata": {
                                    "pa_candidate_id": entry.candidate_id,
                                    "pa_candidate_id_num": entry.candidate_id_num,
                                    "pa_party_raw": entry.party,
                                    "pa_candidate_type_raw": entry.type_val,
                                    "pa_cf_online_url": entry.cf_online_url,
                                },
                            },
                        )
                        seen_candidate_pks.add(cand.pk)
                        total_created += 1

                # Mark absent candidates as withdrawn
                withdrawn = (
                    Candidate.objects
                    .filter(
                        race__election=election,
                        source_metadata__has_key="pa_candidate_id",
                        candidate_status=Candidate.CandidateStatus.RUNNING,
                    )
                    .exclude(pk__in=seen_candidate_pks)
                    .update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
                )
                if withdrawn:
                    logger.info("pa_sos.sync_elections.withdrawn count=%d etype=%s", withdrawn, etype)

                cache.set(cache_key, fingerprint, _FINGERPRINT_CACHE_TTL)
                election.last_synced_at = timezone.now()
                election.save(update_fields=["last_synced_at"])

                # Enqueue details sweep for this election
                sync_pa_candidate_details.delay(election.pk)

        sync_log.records_created = total_created
        sync_log.notes = f"races_created={total_races}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])

        return {
            "created_races": total_races,
            "created_candidates": total_created,
        }

    except PaSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("pa_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def sync_pa_candidate_details(self, election_pk: int):
    """
    Stage 1b: enrich candidates with details from CandidateInfo.aspx.
    Reuses browser context across candidates to optimize launch times.
    """
    try:
        election = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("pa_sos.sync_candidate_details.missing_election pk=%d", election_pk)
        return

    candidates_needing_detail = (
        Candidate.objects
        .filter(
            race__election=election,
            source_metadata__has_key="pa_candidate_id",
        )
        .exclude(source_metadata__has_key="pa_details_enriched")
    )

    total = candidates_needing_detail.count()
    if not total:
        logger.info("pa_sos.sync_candidate_details.nothing_to_do election=%d", election_pk)
        return

    logger.info("pa_sos.sync_candidate_details.start election=%d count=%d", election_pk, total)
    enriched = errors = 0

    with PaSosClient() as client:
        for candidate in candidates_needing_detail.iterator():
            cand_id = (candidate.source_metadata or {}).get("pa_candidate_id")
            if not cand_id:
                continue

            try:
                html_str = client.fetch_candidate_detail(int(cand_id))
                detail = parse_candidate_detail(html_str)
            except PaSosRetryableError as exc:
                logger.warning("pa_sos.sync_candidate_details.fetch_failed id=%s: %s", cand_id, exc)
                errors += 1
                continue
            except Exception as exc:
                logger.error("pa_sos.sync_candidate_details.parse_failed id=%s: %s", cand_id, exc)
                errors += 1
                continue

            meta = dict(candidate.source_metadata or {})
            meta.update({
                "pa_approved_date": detail.approved_date,
                "pa_candidate_type": detail.candidate_type,
                "pa_ballot_lottery": detail.ballot_lottery,
                "pa_ballot_position": detail.ballot_position,
                "pa_cross_filed": detail.cross_filed,
                "pa_county": detail.county,
                "pa_municipality": detail.municipality,
                "pa_cf_annual_totals_url": detail.cf_annual_totals_url,
                "pa_details_enriched": True,
            })
            Candidate.objects.filter(pk=candidate.pk).update(source_metadata=meta)
            enriched += 1

    logger.info(
        "pa_sos.sync_candidate_details.done election=%d enriched=%d errors=%d",
        election_pk, enriched, errors,
    )
