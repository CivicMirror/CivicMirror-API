"""
Washington Public Disclosure Commission (PDC) Celery tasks.

sync_wa_pdc_candidates (Stage 2 / Enrichment):
    Fetches candidate contact and registration details (C-1 form information)
    from the PDC SODA API (data.wa.gov resource 3h9x-7bvm.json) for a given election
    and enriches matching Candidate records in CivicMirror.
"""
from __future__ import annotations

import logging
import re

import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Race
from ops.models import SyncLog

logger = logging.getLogger(__name__)

_SOURCE = "wa_pdc"
_SODA_URL = "https://data.wa.gov/resource/3h9x-7bvm.json"


def _clean_name(name: str) -> str:
    """Normalize a name for matching purposes."""
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"\s+", " ", n)
    return n


def _matches_name(candidate_name: str, filer_name: str) -> bool:
    """
    Check if a candidate_name (from election results) matches a filer_name (from PDC).
    Supports middle name omission, nicknames in parentheses, and initials.
    """
    c_name = _clean_name(candidate_name)
    f_name = _clean_name(filer_name)

    # 1. Direct match or substring match
    if c_name == f_name or c_name in f_name or f_name in c_name:
        return True

    # 2. Extract parenthetical nickname at the end: e.g. "JONATHAN BINGLE (Jonathan Bingle)" -> "Jonathan Bingle"
    parentheses = re.findall(r"\(([^)]+)\)", f_name)
    for p in parentheses:
        p_clean = _clean_name(p)
        if c_name == p_clean or p_clean in c_name or c_name in p_clean:
            return True

    # 3. Word set match (ensure first name and last name match)
    c_words = c_name.split()
    f_words = f_name.replace("(", "").replace(")", "").split()
    if len(c_words) >= 2:
        if c_words[0] in f_words and c_words[-1] in f_words:
            return True

    return False


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_wa_pdc_candidates(self, election_id: int):
    """
    Enrich Washington state candidate records with PDC contact and registration details.
    """
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_wa_pdc_candidates",
        status=SyncLog.Status.STARTED,
    )

    try:
        # Fetch active races for Washington in this election
        races = list(
            Race.objects.filter(
                election_id=election_id,
                election__state="WA",
                race_type=Race.RaceType.CANDIDATE,
            ).prefetch_related("candidates")
        )

        if not races:
            logger.info("wa_pdc.sync_candidates: no active candidate races found for WA in election %d", election_id)
            sync_log.notes = f"No active WA candidate races for election {election_id}"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"enriched": 0, "skipped": 0}

        election_year = str(races[0].election.election_date.year)

        # Fetch all candidate registrations for this election year from SODA
        # We query all records at once with a limit of 5000 to minimize API requests
        params = {
            "election_year": election_year,
            "$limit": "5000",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        logger.info("wa_pdc.sync_candidates: fetching PDC registrations for year %s", election_year)
        resp = requests.get(_SODA_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        pdc_records = resp.json()
        logger.info("wa_pdc.sync_candidates: retrieved %d registrations", len(pdc_records))

        enriched_count = 0
        skipped_count = 0

        # Group PDC records by office name (lowercase) to speed up matching
        records_by_office: dict[str, list[dict]] = {}
        for rec in pdc_records:
            office = (rec.get("office") or "").strip().lower()
            records_by_office.setdefault(office, []).append(rec)

        for race in races:
            # Match office title (e.g. "STATE REPRESENTATIVE")
            office_key = race.office_title.strip().lower()
            office_records = records_by_office.get(office_key, pdc_records)

            for candidate in race.candidates.all():
                match = None
                for rec in office_records:
                    filer_name = rec.get("filer_name", "")
                    if _matches_name(candidate.name, filer_name):
                        # Verify legislative district match if applicable
                        race_dist = (race.jurisdiction or "").strip().lower()
                        rec_dist = (rec.get("legislative_district") or "").strip().lower()

                        # E.g. "LEG DISTRICT 06" and "06"
                        if rec_dist and rec_dist not in race_dist and race_dist not in rec_dist:
                            continue

                        match = rec
                        break

                if not match:
                    # Fallback search across all records if office filter had no match
                    for rec in pdc_records:
                        filer_name = rec.get("filer_name", "")
                        if _matches_name(candidate.name, filer_name):
                            match = rec
                            break

                if match:
                    with transaction.atomic():
                        # Set phone number directly
                        phone = match.get("candidate_committee_phone", "")
                        if phone:
                            candidate.contact_phone = phone

                        # Enrich metadata
                        meta = dict(candidate.source_metadata or {})
                        meta.update({
                            "pdc_personal_email": match.get("candidate_email"),
                            "pdc_campaign_email": match.get("committee_email"),
                            "pdc_registration_url": match.get("url", {}).get("url") if isinstance(match.get("url"), dict) else match.get("url"),
                            "pdc_treasurer_name": match.get("treasurer_name"),
                            "pdc_treasurer_phone": match.get("treasurer_phone"),
                            "pdc_committee_id": match.get("committee_id"),
                            "pdc_candidacy_id": match.get("candidacy_id"),
                            "pdc_filer_id": match.get("filer_id"),
                        })
                        candidate.source_metadata = meta
                        candidate.save()
                        enriched_count += 1
                else:
                    skipped_count += 1

        sync_log.records_created = 0
        sync_log.records_updated = enriched_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        logger.info(
            "wa_pdc.sync_candidates.completed election_id=%d enriched=%d skipped=%d",
            election_id, enriched_count, skipped_count,
        )
        return {"enriched": enriched_count, "skipped": skipped_count}

    except Exception as exc:
        logger.exception("wa_pdc.sync_candidates.failed election_id=%d", election_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
