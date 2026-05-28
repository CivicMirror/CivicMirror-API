"""Source-independent normalization and canonical-key construction."""
import re
from datetime import date

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")

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


def normalize_office_title(title: str) -> str:
    return _squash(title).lower()


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
    """Map a source party label to a canonical code; unknown labels upper-cased."""
    key = _squash(party).lower()
    if not key:
        return ""
    if key in _PARTY_CODES:
        return _PARTY_CODES[key]
    return _squash(party).upper()


def election_canonical_key(
    state: str, election_type: str, election_date: date, jurisdiction_level: str
) -> str:
    return f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"


def race_canonical_key(
    election_key: str, office_title: str, ocd_division_id: str, race_type: str
) -> str:
    return "|".join([
        election_key,
        normalize_office_title(office_title),
        ocd_division_id or "NO_OCD",
        race_type,
    ])
