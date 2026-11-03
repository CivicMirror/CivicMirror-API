from __future__ import annotations

import re

from elections.models import Candidate

_PARTY_MAP = {
    "democratic": "DEM",
    "democrat": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "working class": "WCP",
    "natural law": "NLP",
    "us taxpayers": "UST",
    "u.s. taxpayers": "UST",
    "nonpartisan": "NPA",
    "non-partisan": "NPA",
    "no party affiliation": "NPA",
    # The Party/Incumbent column carries this instead of a party for non-partisan
    # offices; it is an incumbency marker, never a party.
    "incumbent": "",
}
# The general listing labels parties "Democratic Party", "Green Party", ... while the
# primary listing says "Democratic", "Green". Without stripping the suffix the lookup
# missed and the fallback truncation produced "GRE" for Green and "U.S" for the U.S.
# Taxpayers Party, neither of which matches the canonical codes.
_PARTY_SUFFIX_RE = re.compile(r"\s+party$", re.IGNORECASE)


def party_abbrev(raw_party: str) -> str:
    normalized = " ".join((raw_party or "").split()).lower()
    if normalized in _PARTY_MAP:
        return _PARTY_MAP[normalized]
    stripped = _PARTY_SUFFIX_RE.sub("", normalized).strip()
    if stripped in _PARTY_MAP:
        return _PARTY_MAP[stripped]
    return stripped.upper()[:3]


def candidate_status(raw_status: str) -> str:
    status = (raw_status or "").strip().upper()
    if status == "WITHD":
        return Candidate.CandidateStatus.WITHDRAWN
    if status == "DISQ":
        return Candidate.CandidateStatus.DISQUALIFIED
    return Candidate.CandidateStatus.RUNNING


def normalize_office_title(raw_office: str) -> str:
    office = " ".join((raw_office or "").split())
    upper = office.upper()

    prefix_district = re.search(r"^(\d+)(?:ST|ND|RD|TH)?\s+DISTRICT", upper)
    suffix_district = re.search(r"(\d+)(?:ST|ND|RD|TH)?\s+DISTRICT", upper)
    district_match = prefix_district or suffix_district
    district = district_match.group(1) if district_match else ""

    # Statewide boards come first: "Governor of Wayne State University" is a
    # university governing-board seat, and a bare "GOVERNOR" substring test put its
    # candidates on Michigan's gubernatorial ballot.
    if "STATE BOARD OF EDUCATION" in upper:
        return "State Board of Education"
    if "REGENT OF THE UNIVERSITY OF MICHIGAN" in upper:
        return "Regent of the University of Michigan"
    if "TRUSTEE OF MICHIGAN STATE UNIVERSITY" in upper:
        return "Trustee of Michigan State University"
    if "GOVERNOR OF WAYNE STATE UNIVERSITY" in upper:
        return "Governor of Wayne State University"
    # Containment rather than a prefix test, so a results feed that prefixes the
    # contest (e.g. "STATE OF MICHIGAN - GOVERNOR") still matches the race. The
    # university boards are already returned above; the two phrase guards keep any
    # other governing-board wording out.
    if (
        "GOVERNOR" in upper
        and "LIEUTENANT" not in upper
        and "BOARD OF GOVERNORS" not in upper
        and "UNIVERSITY" not in upper
    ):
        return "Governor"
    if "LIEUTENANT GOVERNOR" in upper:
        return "Lieutenant Governor"
    if "SECRETARY OF STATE" in upper:
        return "Secretary of State"
    if "ATTORNEY GENERAL" in upper:
        return "Attorney General"
    # The general listing words these offices differently from the primary listing
    # ("U.S. Senate" vs "United States Senator", "Representative in Congress" vs
    # "United States Representative", "Representative in State Legislature" vs
    # "State Representative"), so both spellings must normalize to one title —
    # results feeds go through this same function via result_office_title.
    if "UNITED STATES SENATOR" in upper or "U.S. SENATOR" in upper or "U.S. SENATE" in upper:
        return "U.S. Senate"
    if (
        "UNITED STATES REPRESENTATIVE" in upper
        or "U.S. REPRESENTATIVE" in upper
        or "REPRESENTATIVE IN CONGRESS" in upper
    ):
        return f"U.S. House - District {district}" if district else "U.S. House"
    if "STATE SENATOR" in upper:
        return f"State Senate - District {district}" if district else "State Senate"
    if "STATE REPRESENTATIVE" in upper or "REPRESENTATIVE IN STATE LEGISLATURE" in upper:
        return f"State House - District {district}" if district else "State House"
    return office


# Michigan elects these boards statewide, which a title-based inferrer cannot tell:
# elections.geography reads "State Board of Education" as local (its BOARD OF EDUCATION
# rule exists for county boards such as NC's) and does not recognise the university
# governing boards at all.
_STATEWIDE_OFFICES = frozenset({
    "State Board of Education",
    "Regent of the University of Michigan",
    "Trustee of Michigan State University",
    "Governor of Wayne State University",
})


def geography_scope(normalized_office_title: str) -> str:
    """Michigan's geography_scope for an already-normalized office title."""
    from elections.geography import infer_geography_scope

    if normalized_office_title in _STATEWIDE_OFFICES:
        return "statewide"
    return infer_geography_scope(normalized_office_title)


# Michigan's general-election listing gives Governor as a joint ballot line,
# "Benson, Jocelyn / Brinks, Winnie". MVIC's results name only the top of the ticket —
# the 2024 general file lists "STEIN, JILL" under ELECTORS OF PRESIDENT AND
# VICE-PRESIDENT, with no running mate. results.tasks matches candidates outside NC on
# the exact (or case-insensitive) name, so storing the joint line would mean Michigan's
# Governor result rows match nothing and are dropped.
_TICKET_SEPARATOR_RE = re.compile(r"\s*/\s*")


def split_running_mates(candidate_name: str) -> tuple[str, list[str]]:
    """Return (top-of-ticket name, running mates) for a joint ballot line."""
    parts = [
        " ".join(part.split())
        for part in _TICKET_SEPARATOR_RE.split(candidate_name or "")
    ]
    parts = [part for part in parts if part]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def result_office_title(raw_contest: str) -> str:
    return normalize_office_title(raw_contest)


def is_write_in(candidate_name: str) -> bool:
    return "WRITE" in (candidate_name or "").upper()
