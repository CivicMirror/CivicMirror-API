"""
Alabama SOS Celery tasks.

sync_al_elections (Stage 1a):
    Scrapes the year-specific Election Information page and upserts an
    Election row per heading, preserving official document links in
    source_metadata for future certification-parsing work.

sync_al_fcpa_candidates (Stage 1b):
    See mappers.py / parsers.py docstrings for the FCPA cycle-vs-election
    caveat. Populates Race + Candidate rows for Elections that have been
    manually tagged with source_metadata["al_fcpa_election_id"].
"""
from __future__ import annotations

import hashlib
import logging

from celery import shared_task
from celery.exceptions import Retry
from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, ElectionSourceLink, Race
from ops.models import SyncLog

from .client import AlSosClient
from .exceptions import AlSosError, AlSosRetryableError
from .mappers import (
    CORE_OFFICE_IDS,
    build_candidate_name,
    certification_geography_scope,
    geography_scope,
    normalize_office_title,
    party_abbrev,
    select_candidate_certification_links,
)
from .parsers import (
    parse_candidate_certification_pdf,
    parse_election_year_page,
    parse_fcpa_committee_detail,
    parse_fcpa_race_search_response,
)

logger = logging.getLogger(__name__)


def _candidate_source_metadata(race, name: str, party: str, additions: dict) -> dict:
    """Merge AL source details without dropping certification provenance."""
    from aggregation.identity import name_match_key, normalize_party

    matching = next(
        (
            candidate
            for candidate in race.candidates.all()
            if name_match_key(candidate.name) == name_match_key(name)
            and normalize_party(candidate.party) == normalize_party(party)
        ),
        None,
    )
    metadata = dict(matching.source_metadata or {}) if matching else {}
    for key, value in additions.items():
        if key.endswith("_sources"):
            merged = list(metadata.get(key, []))
            for item in value:
                if item not in merged:
                    merged.append(item)
            metadata[key] = merged
        else:
            metadata[key] = value
    return metadata


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_elections(self, year: int | None = None):
    """Stage 1a: upsert AL Election rows from the SOS year page."""
    from aggregation import ingest

    target_year = year or timezone.localdate().year
    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = AlSosClient()
        html = client.fetch_election_year_page(target_year)
        parsed = parse_election_year_page(html)

        created_count = 0
        for entry in parsed:
            # source_metadata is written wholesale by _apply_fields (plain setattr,
            # no deep-merge), and al_sos owns the field's provenance on every run
            # since it's the only source that writes it -- so re-syncing must
            # preserve any human-curated keys already on the row (specifically
            # al_fcpa_election_id, which sync_al_fcpa_candidates depends on)
            # rather than clobbering them with a metadata dict that only knows
            # about al_document_links.
            existing_link = ElectionSourceLink.objects.filter(
                source="al_sos", source_id=entry["source_id"],
            ).select_related("election").first()
            source_metadata = dict(
                (existing_link.election.source_metadata or {}) if existing_link else {}
            )
            source_metadata["al_document_links"] = entry["document_links"]

            election, created = ingest.ingest_election(
                source="al_sos",
                source_id=entry["source_id"],
                identity={
                    "state": "AL",
                    "election_type": entry["election_type"],
                    "election_date": entry["election_date"],
                    "jurisdiction_level": entry["jurisdiction_level"],
                },
                fields={
                    "name": entry["name"],
                    "source_metadata": source_metadata,
                },
            )
            if created:
                created_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = len(parsed) - created_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"parsed": len(parsed), "created": created_count}

    except AlSosRetryableError as exc:
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
        except AlSosRetryableError:
            logger.exception("al_sos.sync_al_elections.failed (retries exhausted)")
            sync_log.error_count = 1
            sync_log.last_error = str(exc)
            sync_log.status = SyncLog.Status.FAILED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
            raise
    except Exception as exc:
        logger.exception("al_sos.sync_al_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_certifications(self, year: int | None = None):
    """Create election-specific races and candidates from SOS certifications."""
    from aggregation import ingest
    from aggregation.identity import name_match_key, normalize_party

    target_year = year or timezone.localdate().year
    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_certifications",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = AlSosClient()
        elections = Election.objects.filter(state="AL", election_date__year=target_year).order_by("election_date", "pk")
        created_races = updated_races = created_candidates = updated_candidates = skipped_documents = 0
        documents_ingested = 0

        for election in elections:
            document_links = (election.source_metadata or {}).get("al_document_links", [])
            selected_links = select_candidate_certification_links(document_links)
            if not selected_links:
                continue

            source_metadata = dict(election.source_metadata or {})
            document_history = list(source_metadata.get("al_certification_documents", []))
            history_by_url = {}
            for item in document_history:
                history_by_url.setdefault(item.get("url"), []).append(item)

            parsed_documents = []
            for link in selected_links:
                content = client.fetch_candidate_certification_pdf(link["url"])
                digest = hashlib.sha256(content).hexdigest()
                previous = next(
                    (item for item in reversed(history_by_url.get(link["url"], [])) if item.get("sha256") == digest),
                    None,
                )
                if previous:
                    previous["last_checked_at"] = timezone.now().isoformat()
                    skipped_documents += 1
                    continue

                rows = parse_candidate_certification_pdf(
                    content,
                    party=link["party"],
                    document_label=link["label"],
                    source_url=link["url"],
                    sha256=digest,
                )
                if not rows:
                    raise AlSosError(f"No candidate rows parsed from Alabama certification: {link['url']}")
                parsed_documents.append((link, digest, rows))

            if not parsed_documents:
                election.source_metadata = source_metadata
                election.save(update_fields=["source_metadata"])
                continue

            election_is_primary = election.election_type in {
                Election.ElectionType.PRIMARY,
                Election.ElectionType.PRIMARY_RUNOFF,
            } or "primary" in election.name.lower()

            with transaction.atomic():
                for link, digest, rows in parsed_documents:
                    source_ref = {
                        "label": link["label"],
                        "url": link["url"],
                        "party": link["party"],
                        "sha256": digest,
                    }
                    seen_races: set[int] = set()
                    for row in rows:
                        party = row["party"]
                        variant = f"al:{party}" if election_is_primary else ""
                        identity = {
                            "office_title": row["office_title"],
                            "ocd_division_id": "",
                            "race_type": Race.RaceType.CANDIDATE,
                        }
                        if variant:
                            identity["contest_variant"] = variant

                        race_fields = {
                            "office_title": row["office_title"],
                            "jurisdiction": "Alabama",
                            "geography_scope": certification_geography_scope(row["office_title"]),
                            "vote_method": Race.VoteMethod.SINGLE_CHOICE,
                            "max_selections": 1,
                            "source": Race.Source.AL_SOS,
                        }
                        if variant:
                            race_fields.update({"party": party, "ballot_type": party})

                        race, race_created = ingest.ingest_race(
                            election=election,
                            source="al_sos",
                            identity=identity,
                            fields=race_fields,
                        )
                        if race.pk not in seen_races:
                            seen_races.add(race.pk)
                            if race_created:
                                created_races += 1
                            else:
                                updated_races += 1
                        race_metadata = dict(race.source_metadata or {})
                        race_metadata["al_certification_ocr_review_required"] = True
                        if variant:
                            race_metadata["contest_variant"] = variant
                        race_sources = list(race_metadata.get("al_certification_sources", []))
                        if not any(
                            item.get("url") == source_ref["url"] and item.get("sha256") == digest
                            for item in race_sources
                        ):
                            race_sources.append(source_ref)
                        race_metadata["al_certification_sources"] = race_sources
                        race.source_metadata = race_metadata
                        race.save(update_fields=["source_metadata"])

                        candidate_metadata = _candidate_source_metadata(
                            race,
                            row["candidate_name"],
                            party,
                            {
                                "al_certification_sources": [source_ref],
                                "al_certification_ocr_review_required": True,
                            },
                        )
                        candidate, candidate_created = ingest.ingest_candidate(
                            race=race,
                            source="al_sos",
                            name=row["candidate_name"],
                            party=party,
                            fields={
                                "candidate_status": Candidate.CandidateStatus.RUNNING,
                                "source_metadata": candidate_metadata,
                            },
                        )
                        if candidate_created:
                            created_candidates += 1
                        else:
                            updated_candidates += 1

                    document_history.append({
                        "label": link["label"],
                        "url": link["url"],
                        "party": link["party"],
                        "sha256": digest,
                        "records_parsed": len(rows),
                        "ingested_at": timezone.now().isoformat(),
                    })
                    documents_ingested += 1

                source_metadata["al_certification_documents"] = document_history
                election.source_metadata = source_metadata
                election.last_synced_at = timezone.now()
                election.save(update_fields=["source_metadata", "last_synced_at"])

        sync_log.records_created = created_candidates
        sync_log.records_updated = updated_candidates
        sync_log.records_skipped = skipped_documents
        sync_log.notes = (
            f"races_created={created_races}; races_updated={updated_races}; "
            f"documents_ingested={documents_ingested}; documents_unchanged={skipped_documents}"
        )
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped", "notes", "status", "completed_at",
        ])
        return {
            "races_created": created_races,
            "races_updated": updated_races,
            "candidates_created": created_candidates,
            "candidates_updated": updated_candidates,
            "documents_ingested": documents_ingested,
            "documents_unchanged": skipped_documents,
        }

    except AlSosRetryableError as exc:
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
        except AlSosRetryableError:
            logger.exception("al_sos.sync_certifications.failed (retries exhausted)")
            sync_log.error_count = 1
            sync_log.last_error = str(exc)
            sync_log.status = SyncLog.Status.FAILED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
            raise
    except Exception as exc:
        logger.exception("al_sos.sync_certifications.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_fcpa_candidates(self):
    """
    Stage 1b: populate Race + Candidate from FCPA for every AL Election
    curated with source_metadata["al_fcpa_election_id"].

    The FCPA "election" filter is cycle-granular for regular statewide-cycle
    years (one ID covers the primary, runoff, and general together) --
    verified live against fcpa.alabamavotes.gov, not assumed. See the plan's
    Global Constraints for the verification (election=102/office=23 returns
    both May-2022-primary-only losers and the November general opponent
    under one ID). A human must set this key in Django admin per Election;
    elections without it are skipped entirely.
    """
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_fcpa_candidates",
        status=SyncLog.Status.STARTED,
    )

    try:
        elections = [
            election for election in Election.objects.filter(state="AL")
            if (election.source_metadata or {}).get("al_fcpa_election_id")
        ]

        total_created_races = total_created_candidates = 0
        client = AlSosClient()

        for election in elections:
            fcpa_election_id = election.source_metadata["al_fcpa_election_id"]
            seen_committee_ids: set[int] = set()
            dissolved_committee_ids: set[int] = set()

            for office_id in CORE_OFFICE_IDS:
                page_number = 1
                while True:
                    json_text = client.fetch_fcpa_race_search(fcpa_election_id, office_id, page_number)
                    rows, total_records = parse_fcpa_race_search_response(json_text)
                    if not rows:
                        break

                    for row in rows:
                        committee_id = row["committee_id"]
                        if committee_id in seen_committee_ids:
                            continue
                        seen_committee_ids.add(committee_id)

                        detail_html = client.fetch_fcpa_committee_detail(committee_id)
                        detail = parse_fcpa_committee_detail(detail_html)
                        if detail["dissolved"]:
                            dissolved_committee_ids.add(committee_id)

                        office_title = normalize_office_title(
                            detail["office"], detail["district"], detail.get("place", "")
                        )
                        race, race_created = ingest.ingest_race(
                            election=election,
                            source="al_sos",
                            identity={
                                "office_title": office_title,
                                "ocd_division_id": "",
                                "race_type": "candidate",
                            },
                            fields={
                                "office_title": office_title,
                                "jurisdiction": detail["jurisdiction"] or "Alabama",
                                "geography_scope": geography_scope(office_title),
                            },
                        )
                        if race_created:
                            total_created_races += 1

                        name = build_candidate_name(detail)
                        candidate_source_metadata = _candidate_source_metadata(
                            race,
                            name,
                            party_abbrev(detail["party"]),
                            {
                                "al_fcpa_committee_id": committee_id,
                                "al_committee_status_raw": detail["committeeStatus"],
                            },
                        )
                        candidate, candidate_created = ingest.ingest_candidate(
                            race=race,
                            source="al_sos",
                            name=name,
                            party=party_abbrev(detail["party"]),
                            fields={
                                "candidate_status": (
                                    Candidate.CandidateStatus.WITHDRAWN if detail["dissolved"]
                                    else Candidate.CandidateStatus.RUNNING
                                ),
                                "source_metadata": candidate_source_metadata,
                            },
                        )
                        if candidate_created:
                            total_created_candidates += 1

                    if page_number * 100 >= total_records:
                        break
                    page_number += 1

            if dissolved_committee_ids:
                withdrawn = (
                    Candidate.objects
                    .filter(
                        race__election=election,
                        source_metadata__al_fcpa_committee_id__in=list(dissolved_committee_ids),
                    )
                    .exclude(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
                    .update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
                )
                if withdrawn:
                    logger.info("al_sos.sync_fcpa.dissolved count=%d election=%d", withdrawn, election.pk)

            election.last_synced_at = timezone.now()
            election.save(update_fields=["last_synced_at"])

        sync_log.records_created = total_created_candidates
        sync_log.notes = f"races_created={total_created_races}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])
        return {"races_created": total_created_races, "candidates_created": total_created_candidates}

    except AlSosRetryableError as exc:
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
        except AlSosRetryableError:
            logger.exception("al_sos.sync_al_fcpa_candidates.failed (retries exhausted)")
            sync_log.error_count = 1
            sync_log.last_error = str(exc)
            sync_log.status = SyncLog.Status.FAILED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
            raise
    except Exception as exc:
        logger.exception("al_sos.sync_al_fcpa_candidates.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
