"""Source-independent normalization and canonical-key construction."""
import re
from datetime import date

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

# CA SOS labels party as "Party Preference: Democratic"; strip the prefix so it
# maps to the same code as a terser source label ("Dem").
_PARTY_PREFIX_RE = re.compile(r"^\s*party\s+preference\s*:\s*", re.IGNORECASE)

# Trailing geographic qualifiers that sources append to office titles, e.g.
# CA SOS' "Governor - Statewide Results". "Statewide"/"nationwide" denote a
# single contest per election, so stripping them is safe for every race type.
_GLOBAL_QUALIFIER_RE = re.compile(
    r"\s*[-–—]\s*(statewide|nationwide)(\s+results?)?\s*$",
    re.IGNORECASE,
)
# Local qualifiers can distinguish two same-named *ballot measures* in one
# election (a city Measure A vs a county Measure A), so they are stripped only
# for non-measure races (see normalize_office_title).
_LOCAL_QUALIFIER_RE = re.compile(
    r"\s*[-–—]\s*(districtwide|countywide|citywide)(\s+results?)?\s*$",
    re.IGNORECASE,
)

# Bare 2-letter state/territory codes. civic_api falls back to election.state
# here when a contest has no real OCD id; ca_sos correctly emits none. Treating
# these as "no OCD" lets the two sources key-match. Includes US territories.
_US_STATE_CODES = frozenset([
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
])

# Canonical party codes. Keys are normalized (lowercased) source variants.
_PARTY_CODES = {
    "dem": "DEM", "democratic": "DEM", "democratic party": "DEM", "democrat": "DEM",
    "rep": "REP", "republican": "REP", "republican party": "REP", "gop": "REP",
    "grn": "GRN", "green": "GRN", "green party": "GRN",
    "lib": "LIB", "libertarian": "LIB", "libertarian party": "LIB",
    "pf": "PF", "peace and freedom": "PF",
    "ai": "AI", "american independent": "AI",
    "np": "NP", "nonpartisan": "NP", "no party preference": "NP", "npp": "NP",
    "ind": "IND", "independent": "IND",
}


def _squash(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def normalize_office_title(title: str, race_type: str | None = None) -> str:
    """Lowercase, collapse whitespace, and strip trailing geographic qualifiers.

    "Statewide"/"nationwide" qualifiers are always removed. Local qualifiers
    (districtwide/countywide/citywide) are removed only for non-measure races:
    two distinct local ballot measures in one election can share a name and
    differ only by that qualifier, so stripping it would wrongly merge them.
    """
    cleaned = _GLOBAL_QUALIFIER_RE.sub("", _squash(title))
    if race_type != "measure":
        cleaned = _LOCAL_QUALIFIER_RE.sub("", cleaned)
    return _squash(cleaned).lower()


def _normalize_ocd(ocd_division_id: str) -> str:
    """Collapse a bare state/territory code (a civic_api fallback) to empty so
    it key-matches sources that correctly emit no OCD. Real 'ocd-division/...'
    identifiers pass through unchanged."""
    cleaned = (ocd_division_id or "").strip()
    return "" if cleaned.upper() in _US_STATE_CODES else cleaned


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. No reordering."""
    stripped = _PUNCT_RE.sub("", name or "")
    return _squash(stripped).lower()


def name_match_key(name: str) -> str:
    """
    Order-independent key for candidate matching: normalized tokens sorted, so
    "Xavier Becerra" and "Becerra, Xavier" collapse to the same key.
    """
    return " ".join(sorted(normalize_name(name).split()))


def normalize_party(party: str) -> str:
    """Map a source party label to a canonical code; unknown labels upper-cased.

    Strips a leading "Party Preference:" qualifier first — CA SOS expresses party
    as e.g. "Party Preference: Democratic", which must collapse to the same code
    as another source's "Dem" so the two candidates match instead of duplicating.
    """
    cleaned = _PARTY_PREFIX_RE.sub("", _squash(party)).strip()
    key = cleaned.lower()
    if not key:
        return ""
    if key in _PARTY_CODES:
        return _PARTY_CODES[key]
    return cleaned.upper()


def election_canonical_key(
    state: str, election_type: str, election_date: date, jurisdiction_level: str
) -> str:
    return f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"


def race_canonical_key(
    election_key: str, office_title: str, ocd_division_id: str, race_type: str
) -> str:
    return "|".join([
        election_key,
        normalize_office_title(office_title, race_type),
        _normalize_ocd(ocd_division_id) or "NO_OCD",
        race_type,
    ])
