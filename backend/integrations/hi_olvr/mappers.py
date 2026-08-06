from __future__ import annotations

from datetime import date

from elections.models import Election, Race

from .parsers import HawaiiCandidateRow, candidate_row_hash


def hi_primary_election_date() -> date:
    return date(2026, 8, 8)


def map_election() -> dict:
    election_date = hi_primary_election_date()
    return {
        "source_id": "hi_olvr_2026_primary",
        "name": "2026 Hawaii Primary Election",
        "election_date": election_date,
        "election_type": "primary",
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "HI",
        "status": Election.Status.UPCOMING,
    }


def normalize_contest_title(contest: str) -> str:
    return " ".join((contest or "").strip().split())


def geography_scope_for_contest(contest: str) -> str:
    text = (contest or "").lower()
    if "county" in text:
        return "county"
    if "district" in text or "dist " in text or "district " in text:
        return "district"
    return "statewide"


def contest_variant_for_row(row: HawaiiCandidateRow) -> str:
    contest = normalize_contest_title(row.contest).lower()
    party = " ".join((row.party or "").split()).lower()
    return f"hi:{contest}:{party}"


def map_race_fields(row: HawaiiCandidateRow, report_url: str, elid: str) -> dict:
    contest = normalize_contest_title(row.contest)
    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": contest,
        "jurisdiction": "Hawaii",
        "geography_scope": geography_scope_for_contest(contest),
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.HI_OLVR,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ballot_type": "primary",
        "party": row.party,
        "source_links": [report_url],
        "supporting_links": [report_url],
        "source_metadata": {
            "hi_olvr_report_url": report_url,
            "hi_olvr_elid": elid,
            "hi_olvr_contest": row.contest,
            "hi_olvr_party": row.party,
            "hi_olvr_status": row.status,
        },
        "contest_variant": contest_variant_for_row(row),
    }


def map_candidate_fields(row: HawaiiCandidateRow, report_url: str, elid: str) -> dict:
    return {
        "party": row.party,
        "incumbent": False,
        "candidate_status": "running",
        "source_metadata": {
            "hi_olvr_report_url": report_url,
            "hi_olvr_elid": elid,
            "hi_olvr_contest": row.contest,
            "hi_olvr_legal_name": row.legal_name,
            "hi_olvr_ballot_name": row.ballot_name,
            "hi_olvr_status": row.status,
            "hi_olvr_issue_date": row.issue_date.isoformat() if row.issue_date else "",
            "hi_olvr_filing_date": row.filing_date.isoformat() if row.filing_date else "",
            "hi_olvr_row_hash": candidate_row_hash(row),
        },
    }
