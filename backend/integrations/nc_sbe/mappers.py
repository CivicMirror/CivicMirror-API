"""
Static helpers and normalization for the NC SBE integration.

Election type heuristic:
    November     → general
    March / May  → primary
    everything else → special

This covers:
    - General elections (November)
    - State primaries (historically March, occasionally May for runoffs)
    - Municipal/special elections (varied dates)

Contest type codes from the TSV:
    S — Statewide (state legislative, federal, judicial)
    C — County/City (county commissioner, mayor, school board, etc.)

Write-in detection: "Write-In" anywhere in the Choice string (case-insensitive).
"""
from __future__ import annotations

import datetime


def election_type_from_date(d: datetime.date) -> str:
    if d.month == 11:
        return "general"
    if d.month in (3, 5):
        return "primary"
    return "special"


def election_name(d: datetime.date) -> str:
    etype = election_type_from_date(d)
    label = {
        "general": "General Election",
        "primary": "Primary Election",
        "special": "Special Election",
    }[etype]
    return f"{d.year} North Carolina {label} ({d.strftime('%B %-d')})"


def geography_scope(contest_type_code: str) -> str:
    """Map NC contest type code to canonical geography_scope string."""
    return "statewide" if contest_type_code.upper() == "S" else "local"


def is_write_in(choice: str) -> bool:
    return "write-in" in choice.lower()


# ---------------------------------------------------------------------------
# Stage 1 — Candidate Filing CSV mappers
#
# Source: Elections/{YEAR}/Candidate Filing/Candidate_Listing_{YEAR}.csv on
# the same public S3 bucket the results adapter reads.
#
# Full Core scope (per ADR-005/COVERAGE-CLARIFICATION): federal + statewide
# executive + state legislative offices only. Judicial (Supreme Court, Court
# of Appeals, District Court, District Attorney) and all county/local offices
# are out of scope for now, matching the same office-group scoping decision
# already made for KY (docs/superpowers/specs/2026-07-14-ky-sos-adapter-design.md).
#
# contest_name already fully disambiguates a race (district number embedded
# in the string, e.g. "NC STATE SENATE DISTRICT 01"); the same contest_name
# repeats once per county the district spans, so races are deduplicated by
# contest_name across counties. Within a contest_name, the CSV also carries
# separate primary-per-party rows (party_contest set, e.g. "REP") and a
# single general-election row (party_contest blank) — contest_variant_key
# keeps those distinct, mirroring VT's contest_variant pattern.
# ---------------------------------------------------------------------------

_IN_SCOPE_PREFIXES = (
    "US SENATE",
    "US HOUSE OF REPRESENTATIVES",
    "NC STATE SENATE",
    "NC HOUSE OF REPRESENTATIVES",
    "GOVERNOR",
    "LIEUTENANT GOVERNOR",
    "ATTORNEY GENERAL",
    "SECRETARY OF STATE",
    "STATE TREASURER",
    "STATE AUDITOR",
    "COMMISSIONER OF AGRICULTURE",
    "COMMISSIONER OF INSURANCE",
    "COMMISSIONER OF LABOR",
    "SUPERINTENDENT OF PUBLIC INSTRUCTION",
)


def is_in_scope_contest(contest_name: str) -> bool:
    name = (contest_name or "").strip().upper()
    return name.startswith(_IN_SCOPE_PREFIXES)


def parse_candidate_filing_date(raw: str) -> datetime.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        return None


def contest_variant_key(contest_name: str, party_contest: str) -> str:
    """
    nc:{contest_name}:{party-code-or-general}

    Threaded through aggregation.identity.race_canonical_key's optional
    contest_variant parameter — without it, a district's multi-candidate
    party primary and its single-nominee general contest (same contest_name)
    would collapse into one Race.
    """
    party = (party_contest or "").strip().upper() or "general"
    return f"nc:{(contest_name or '').strip().upper()}:{party}"


def geography_scope_for_contest(contest_name: str) -> str:
    return "district" if "DISTRICT" in (contest_name or "").upper() else "statewide"


def map_race_identity(
    contest_name: str,
    party_contest: str,
    is_partisan: bool,
    vote_for: int,
    term: str,
) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    (contest_name, party_contest) group of Candidate_Listing rows.
    """
    from elections.models import Race

    office_title = (contest_name or "").strip()
    variant = contest_variant_key(office_title, party_contest)
    vote_for = max(1, int(vote_for or 1))

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "North Carolina",
        "geography_scope": geography_scope_for_contest(office_title),
        "vote_method": Race.VoteMethod.MULTI_SEAT if vote_for > 1 else Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": vote_for,
        "ballot_type": (party_contest or "").strip(),
        "source": Race.Source.NC_SBE,
        "source_metadata": {
            "provider": "nc_sbe",
            "contest_name": office_title,
            "party_contest": (party_contest or "").strip(),
            "is_partisan": bool(is_partisan),
            "vote_for": vote_for,
            "term_years": (term or "").strip(),
            "contest_variant": variant,
        },
    }
    return identity, fields


def group_candidate_rows(rows: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    """
    Group Candidate_Listing rows by (election_dt, contest_name, party_contest).

    party_contest is non-blank only on primary-ballot rows (one group per
    party's primary); it's blank on general-election rows (one group per
    contest, all parties' nominees together) — see contest_variant_key.
    """
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (
            (row.get("election_dt") or "").strip(),
            (row.get("contest_name") or "").strip(),
            (row.get("party_contest") or "").strip(),
        )
        groups.setdefault(key, []).append(row)
    return groups


def dedupe_candidate_rows(rows: list[dict]) -> list[dict]:
    """
    Collapse rows repeated once per county a district spans down to one row
    per candidate (by name_on_ballot), keeping first-seen order.
    """
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in rows:
        name = (row.get("name_on_ballot") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(row)
    return deduped


def map_candidate(row: dict) -> dict:
    """Map a Candidate_Listing CSV row to Candidate model fields."""
    from elections.models import Candidate

    return {
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "provider": "nc_sbe",
            "candidacy_date": (row.get("candidacy_dt") or "").strip(),
        },
    }
