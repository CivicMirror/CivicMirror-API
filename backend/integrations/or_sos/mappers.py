from __future__ import annotations

import datetime
import re

from elections.models import Candidate, Election, Race

from .parsers import OrCandidateFiling, OrElectionInfo, OrLocalMeasure, OrOpenOffice

_MONTH_FORMAT = "%B %d, %Y"
_ORESTAR_ELECTION_IDS = {
    (2026, Election.ElectionType.PRIMARY): "1451",
    (2026, Election.ElectionType.GENERAL): "1453",
}


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def infer_election_status(election_date: datetime.date) -> str:
    from django.utils import timezone as tz

    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def parse_election_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value, _MONTH_FORMAT).date()


def map_election(info: OrElectionInfo) -> dict:
    election_date = parse_election_date(info.election_date)
    election_type = info.election_type if info.election_type in Election.ElectionType.values else Election.ElectionType.OTHER
    year = election_date.year
    return {
        "source_id": f"or_sos_{year}_{election_type}_{election_date:%Y%m%d}",
        "name": info.name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "OR",
        "status": infer_election_status(election_date),
        "source_metadata": {
            "source_url": info.source_url,
            "or_sos_election_date_text": info.election_date,
            "or_sos_orestar_election_id": _ORESTAR_ELECTION_IDS.get((year, election_type), ""),
        },
    }


def normalize_orestar_office(office: str) -> tuple[str, str, str, str]:
    """Return office_title, ocd_division_id, geography_scope, district from ORESTAR office text."""
    district = _extract_ordinal_district(office)
    lower = normalize(office)
    if lower.startswith("us representative") and district:
        return (
            f"U.S. Representative, District {district}",
            f"ocd-division/country:us/state:or/cd:{district}",
            "district",
            district,
        )
    if lower.startswith("state representative") and district:
        return (
            f"Oregon State Representative, District {district}",
            f"ocd-division/country:us/state:or/sldl:{district}",
            "district",
            district,
        )
    if lower.startswith("state senator") and district:
        return (
            f"Oregon State Senate, District {district}",
            f"ocd-division/country:us/state:or/sldu:{district}",
            "district",
            district,
        )
    if lower == "governor":
        return "Governor", "ocd-division/country:us/state:or", "statewide", ""
    if lower in {"us senator", "u.s. senator"}:
        return "U.S. Senator", "ocd-division/country:us/state:or", "statewide", ""
    return office, "ocd-division/country:us/state:or", "statewide", district


def map_race_from_candidate_filing(election_obj: Election, filing: OrCandidateFiling) -> dict:
    office_title, ocd_id, geography_scope, district = normalize_orestar_office(filing.office)
    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )
    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": f"Oregon District {district}" if district else "Oregon",
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.OR_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": ocd_id,
        "normalized_office_title": normalize(office_title),
        "source_metadata": {
            "or_sos_office_raw": filing.office,
            "district": district,
            "source": "orestar_candidate_filings",
        },
    }


def map_candidate(filing: OrCandidateFiling) -> dict:
    return {
        "party": filing.party,
        "incumbent": False,
        "candidate_status": (
            Candidate.CandidateStatus.RUNNING
            if filing.qualified.lower() == "yes"
            else Candidate.CandidateStatus.DISQUALIFIED
        ),
        "source_metadata": {
            "or_sos_election": filing.election,
            "or_sos_filing_method": filing.filing_method,
            "or_sos_filing_date": filing.filing_date,
            "or_sos_qualified": filing.qualified,
        },
    }


def map_measure_race(election_obj: Election, measure: OrLocalMeasure) -> dict:
    office_title = f"Oregon Measure {measure.measure_number}: {measure.ballot_title_caption}"
    return {
        "race_type": Race.RaceType.MEASURE,
        "office_title": office_title,
        "jurisdiction": f"{measure.county} County, Oregon" if measure.county else "Oregon",
        "geography_scope": "county" if measure.county else "statewide",
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.OR_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.YES_NO,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(office_title),
        "source_metadata": {
            "or_sos_measure_number": measure.measure_number,
            "or_sos_election": measure.election,
            "county": measure.county,
            "source": "orestar_local_measures",
        },
    }


def _extract_ordinal_district(value: str) -> str:
    match = re.search(r"(\d+)(?:st|nd|rd|th)?\s+district", value or "", flags=re.IGNORECASE)
    return str(int(match.group(1))) if match else ""


def map_race(election_obj: Election, office: OrOpenOffice, source_url: str = "") -> dict:
    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    jurisdiction = f"Oregon District {office.district}" if office.district else "Oregon"

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office.office_title,
        "jurisdiction": jurisdiction,
        "geography_scope": office.geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.OR_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": office.ocd_division_id,
        "normalized_office_title": normalize(office.office_title),
        "source_links": [source_url] if source_url else [],
        "source_metadata": {
            "or_sos_office_code": office.office_code,
            "district": office.district,
            "source": "open_offices_pdf",
        },
    }
