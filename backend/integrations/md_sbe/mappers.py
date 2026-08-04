"""
Stage 1 mappers for the MD SBE integration.

Source: consolidated {PREFIX}{yy}_statewide_candidatelist.csv, confirmed
2026-08-04 to carry every in-scope office in one file (585 rows for the
2026 primary cycle) — see docs/state-research/MD/MD-Election_Research.md
Rank 2 and the plan's "Live-Verified Source Facts" section.

Full Core scope for this wave (per ADR-005/COVERAGE-CLARIFICATION, same
convention as NC/KY/VT): federal + state legislative + state executive
offices only. Judicial (Judge of the Circuit Court, appellate retention)
and all county/local/municipal offices are out of scope.
"""
from __future__ import annotations

import csv
import io
import re

IN_SCOPE_OFFICES: frozenset[str] = frozenset({
    "Governor / Lt. Governor",
    "Attorney General",
    "Comptroller",
    "U.S. Senator",
    "Representative in Congress",
    "State Senator",
    "House of Delegates",
})


def is_in_scope_office(office_name: str) -> bool:
    return (office_name or "").strip() in IN_SCOPE_OFFICES


# ---------------------------------------------------------------------------
# Shared normalization — the bridge between the candidate CSV (Stage 1 races)
# and the per-county results CSVs (results adapter).
#
# The two feeds spell the same contest differently:
#
#     candidate CSV  "Contest Run By District Name and Number" = "Legislative District 1A"
#     results CSV    "Office District"                          = "01A"
#     candidate CSV  "Office Political Party"                   = "Democratic"
#     results CSV    "Party"                                     = "DEM"
#
# (all four verified live 2026-08-04). Normalizing both sides to one key lets
# a ResultRow carry a contest_code/party_code that matches the Race's
# source_metadata exactly — see results/adapters/md_aggregate.py and
# results/tasks.py::_race_source_identity.
# ---------------------------------------------------------------------------

_STATEWIDE_DISTRICT_LABELS = frozenset({"", "state of maryland"})
_DISTRICT_SUFFIX_RE = re.compile(r"(\d+)\s*([A-Za-z]?)\s*$")

_DISTRICT_LABEL_BY_OFFICE: dict[str, str] = {
    "Representative in Congress": "Congressional District",
    "State Senator": "Legislative District",
    "House of Delegates": "Legislative District",
}

_PARTY_CODES: dict[str, str] = {
    "DEMOCRATIC": "DEM", "DEM": "DEM",
    "REPUBLICAN": "REP", "REP": "REP",
    "GREEN": "GRN", "GRN": "GRN",
    "LIBERTARIAN": "LIB", "LIB": "LIB",
    "UNAFFILIATED": "UNA", "UNA": "UNA",
    "OTHER CANDIDATES": "OTC", "OTC": "OTC",
    "JUDICIAL": "JUD", "JUD": "JUD",
    "NON-PARTISAN": "NON", "NONPARTISAN": "NON", "NON": "NON",
}


def normalize_district_key(district: str) -> str:
    """Canonical district key: zero-padded number + optional letter, or "".

    "Legislative District 1A" -> "01A"    (candidate CSV)
    "01A"                      -> "01A"    (results CSV)
    "Congressional District 6" -> "06"
    "State Of Maryland" / ""   -> ""       (statewide)
    """
    raw = " ".join((district or "").strip().split())
    if raw.lower() in _STATEWIDE_DISTRICT_LABELS:
        return ""
    match = _DISTRICT_SUFFIX_RE.search(raw)
    if not match:
        return raw.upper()
    return f"{int(match.group(1)):02d}{match.group(2).upper()}"


def district_display(office_name: str, district_key: str) -> str:
    """Render a district key back to MD's own candidate-CSV spelling."""
    if not district_key:
        return ""
    label = _DISTRICT_LABEL_BY_OFFICE.get((office_name or "").strip(), "District")
    number = district_key.lstrip("0") or district_key
    return f"{label} {number}"


def normalize_party_key(party: str) -> str:
    """Canonical party code shared by both feeds ("Democratic"/"DEM" -> "DEM")."""
    raw = " ".join((party or "").strip().upper().split())
    return _PARTY_CODES.get(raw, raw)


def race_office_title(office_name: str, district: str) -> str:
    """Race.office_title for an (office, district) pair, from EITHER feed's
    district spelling — the single source of truth for MD race titles."""
    office_name = (office_name or "").strip()
    district_key = normalize_district_key(district)
    if not district_key:
        return office_name
    return f"{office_name} - {district_display(office_name, district_key)}"


def race_contest_code(office_name: str, district: str) -> str:
    """Party-agnostic contest identity, stored on Race.source_metadata
    ["contest_code"] and emitted on every ResultRow's raw dict."""
    return f"md:{(office_name or '').strip()}:{normalize_district_key(district)}"


def contest_variant_key(office_name: str, district: str, party: str) -> str:
    """
    md:{office}:{district-key}:{party-code-or-general}

    Threaded through aggregation.identity.race_canonical_key's contest_variant
    parameter. MD groups every party's candidates for a primary contest under
    one Office Name/district row-set — only "Office Political Party" tells them
    apart — so without this the Democratic and Republican Governor primaries
    would collapse into a single Race. Mirrors nc_sbe's contest_variant_key,
    including its "general" fallback for a blank party.
    """
    party_code = normalize_party_key(party) or "general"
    return f"md:{(office_name or '').strip()}:{normalize_district_key(district)}:{party_code}"


def parse_statewide_candidate_csv(csv_text: str) -> list[dict]:
    """Parse the consolidated statewide candidate-list CSV into row dicts.

    Maps by header name (csv.DictReader), never by column position — MD's
    schema has drifted between cycles before.
    """
    # Strip UTF-8 BOM if present (MD's exports include it)
    if csv_text.startswith('﻿'):
        csv_text = csv_text[1:]
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def group_candidate_rows(
    rows: list[dict], split_by_party: bool = False,
) -> dict[tuple[str, str, str], list[dict]]:
    """Group candidate rows into one group per race.

    Key is always (Office Name, district, party) — but `party` is only
    populated when `split_by_party` is set, which the caller does for the
    PRIMARY phase only.

    Why not unconditionally: MD's two candidate CSVs have different shapes
    (both verified live 2026-08-04).

      primary  2026_GP_statewide_candidatelist.csv — every party's candidates
               for a contest share one Office Name/district; "Office Political
               Party" is the ONLY discriminator, and each party's ballot is a
               separate race. Must split.
      general  2026_GG_statewide_candidatelist.csv — one nominee per party per
               contest, all competing in the SAME race (Governor/Lt. Governor
               lists Democratic, Republican, Green and Working Class Party
               rows). Splitting here would wrongly create four one-candidate
               races instead of one four-candidate race.
    """
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (
            (row.get("Office Name") or "").strip(),
            (row.get("Contest Run By District Name and Number") or "").strip(),
            (row.get("Office Political Party") or "").strip() if split_by_party else "",
        )
        groups.setdefault(key, []).append(row)
    return groups


def map_race_identity(office_name: str, district: str, party: str = "") -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    (office_name, district, party) group of statewide candidate-list rows.

    `party` is non-blank only for primary-ballot groups; it folds into
    contest_variant (and Race.party / Race.ballot_type) exactly as nc_sbe does,
    so each party's primary for a contest becomes its own Race.
    """
    from elections.models import Race

    office_name = (office_name or "").strip()
    party = (party or "").strip()
    district_key = normalize_district_key(district)
    is_statewide = district_key == ""
    office_title = race_office_title(office_name, district)
    variant = contest_variant_key(office_name, district, party)
    contest_code = race_contest_code(office_name, district)
    party_code = normalize_party_key(party)

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Maryland",
        "geography_scope": "statewide" if is_statewide else "district",
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ballot_type": party,
        "party": party,
        "source": Race.Source.MD_SBE,
        "source_metadata": {
            "provider": "md_sbe",
            "office_name": office_name,
            "district": (district or "").strip(),
            "district_key": district_key,
            "contest_variant": variant,
            # results/tasks.py::_race_source_identity reads these two keys to
            # match ResultRows to this race without relying on office_title
            # string equality (the results CSV spells districts differently).
            # party_code is deliberately omitted for a general-election race so
            # its identity stays party-agnostic and matches every nominee's rows.
            "contest_code": contest_code,
            **({"party_code": party_code} if party_code else {}),
        },
    }
    return identity, fields


def candidate_display_name(row: dict) -> str:
    """
    Build the ballot display name. Governor/Lt. Governor rows combine the
    primary candidate and their running mate into one "A and B" line — there
    is no ticket/running_mate field on the Candidate model, so this is the
    single Candidate row's name for that race. Both individual names are
    preserved separately in map_candidate's source_metadata for provenance.

    The " and " separator is not cosmetic: MD's own results CSVs render the
    ticket exactly this way ("Wes Moore and Aruna Miller", verified live
    2026-08-04 in GP26_01DemocraticResults.csv), and aggregation/ingest.py
    matches result rows to candidates via name_match_key — a " / " join would
    never reconcile.
    """
    last = (row.get("Candidate Ballot Last Name and Suffix") or "").strip()
    first = (row.get("Candidate First Name and Middle Name") or "").strip()
    primary_name = f"{first} {last}".strip()

    has_related = (row.get("Has Related Candidate") or "").strip().lower() == "yes"
    if not has_related:
        return primary_name

    related_last = (row.get("Related Candidate Last Name and Suffix") or "").strip()
    related_first = (row.get("Related Candidate First Name and Middle Name") or "").strip()
    related_name = f"{related_first} {related_last}".strip()
    if not related_name:
        return primary_name
    return f"{primary_name} and {related_name}"


def map_candidate(row: dict) -> dict:
    """Map a statewide candidate-list CSV row to Candidate model fields."""
    from elections.models import Candidate

    status_raw = (row.get("Candidate Status") or "").strip()
    status_map = {
        "active": Candidate.CandidateStatus.RUNNING,
        "withdrawn": Candidate.CandidateStatus.WITHDRAWN,
        "disqualified": Candidate.CandidateStatus.DISQUALIFIED,
    }
    candidate_status = status_map.get(status_raw.lower(), Candidate.CandidateStatus.RUNNING)

    return {
        "candidate_status": candidate_status,
        "source_metadata": {
            "provider": "md_sbe",
            "md_status": status_raw,
            "filing": (row.get("Filing Type and Date") or "").strip(),
            # Both halves of a Governor/Lt. Governor ticket keep their raw
            # names here — the display name is a join, so neither half should
            # only be recoverable by string-subtracting the other.
            "primary_candidate_last_name": (row.get("Candidate Ballot Last Name and Suffix") or "").strip(),
            "primary_candidate_first_name": (row.get("Candidate First Name and Middle Name") or "").strip(),
            "related_candidate_last_name": (row.get("Related Candidate Last Name and Suffix") or "").strip(),
            "related_candidate_first_name": (row.get("Related Candidate First Name and Middle Name") or "").strip(),
        },
    }
