"""
Office title and candidate name normalization for New Jersey's per-county
Clarity results.

NJ has no state-level results aggregator, so office titles and candidate
names for the SAME statewide contest are not consistent strings across
counties. Confirmed live 2026-07-12 across 5 counties for one contest
(2026 US Senate primary, DEM):
    "DEM U.S. Senator"             (Atlantic)
    "US Senate (DEM)"              (Burlington)
    "United States Senator (DEM)"  (Essex)
    "U.S. Senate (DEM)"            (Mercer)
    "DEM UNITED STATES SENATE"     (Ocean)
And candidate names:
    "Cory BOOKER"       (Atlantic, Mercer)
    "Cory Booker"       (Burlington, Essex)
    "DEM Cory BOOKER"   (Ocean — party embedded in the name field itself)

canonical_office_title() embeds the party for primaries (not generals)
because results/tasks.py::_bootstrap_races_from_results groups rows into
Race records purely by office_title string. Clarity represents each
party's primary as a SEPARATE contest with its own candidate list —
without the party embedded, a Dem primary and Rep primary for the same
office would incorrectly merge into one Race.
"""
from __future__ import annotations

import re

_PARTY_TOKENS = frozenset({"DEM", "REP", "GOP", "IND", "UNA", "CON", "LIB", "GRN"})

_NON_CANDIDATE_NAMES = frozenset({
    "write-in", "writein", "personal choice", "under votes", "over votes", "blank ballots",
})

_CANONICAL_DISPLAY_TITLES: dict[str, str] = {
    "US_SENATE": "UNITED STATES SENATOR",
    "GOVERNOR": "GOVERNOR",
}


def _extract_party(title: str) -> tuple[str, str]:
    """Return (title_with_party_removed, party). party is '' if none found."""
    match = re.search(r'\(([A-Z]{2,4})\)', title)
    if match and match.group(1) in _PARTY_TOKENS:
        return title[:match.start()] + title[match.end():], match.group(1)

    words = title.split()
    if words and words[0].upper() in _PARTY_TOKENS:
        return " ".join(words[1:]), words[0].upper()
    if words and words[-1].upper() in _PARTY_TOKENS:
        return " ".join(words[:-1]), words[-1].upper()

    return title, ""


def normalize_office(raw_title: str) -> tuple[str, str]:
    """Return (canonical_office_key, party) for a raw Clarity contest title."""
    title, party = _extract_party(raw_title.strip())

    norm = title.upper().replace(".", "").replace(",", "")
    norm = " ".join(norm.split())

    if re.fullmatch(r'(US SENAT(OR|E)|UNITED STATES SENAT(OR|E))', norm):
        key = "US_SENATE"
    else:
        district_match = re.search(
            r'CONGRESS.*?(\d+)(?:ST|ND|RD|TH)?\s*(?:CONGRESSIONAL)?\s*DISTRICT', norm,
        )
        if district_match:
            key = f"US_HOUSE_{int(district_match.group(1)):02d}"
        elif "GOVERNOR" in norm:
            key = "GOVERNOR"
        else:
            # Unrecognized office phrasing — fall through unchanged. Still
            # usable as a grouping key within a single county, just won't
            # aggregate cross-county under a shared canonical key.
            key = norm

    return key, party


def canonical_office_title(canonical_key: str, party: str) -> str:
    """Human-readable Race.office_title for a canonical office key + party."""
    base = _CANONICAL_DISPLAY_TITLES.get(canonical_key, canonical_key)
    if party:
        return f"{base} ({party} PRIMARY)"
    return base


def normalize_candidate_name(raw_name: str) -> str | None:
    """
    Normalize a candidate name for cross-county matching. Returns None for
    non-candidate bookkeeping rows (write-ins, NJ's "Personal Choice" ballot
    line, under/over votes).
    """
    name = raw_name.strip()
    words = name.split()
    if words and words[0].upper() in _PARTY_TOKENS:
        name = " ".join(words[1:])

    collapsed = " ".join(name.split())
    # Return None for empty results or known non-candidate bookkeeping rows
    if not collapsed or collapsed.lower() in _NON_CANDIDATE_NAMES:
        return None
    return collapsed.upper()
