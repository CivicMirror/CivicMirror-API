import pytest

from results.adapters.nj_normalize import (
    canonical_office_title,
    normalize_candidate_name,
    normalize_office,
)


@pytest.mark.parametrize("raw_title,expected", [
    ("DEM U.S. Senator", ("US_SENATE", "DEM")),
    ("US Senate (DEM)", ("US_SENATE", "DEM")),
    ("United States Senator (DEM)", ("US_SENATE", "DEM")),
    ("U.S. Senate (DEM)", ("US_SENATE", "DEM")),
    ("DEM UNITED STATES SENATE", ("US_SENATE", "DEM")),
    ("REP UNITED STATES SENATE", ("US_SENATE", "REP")),
    ("Member of Congress - 1st Congressional District (DEM)", ("US_HOUSE_01", "DEM")),
])
def test_normalize_office_real_variants(raw_title, expected):
    assert normalize_office(raw_title) == expected


def test_canonical_office_title_embeds_party_for_primary():
    assert canonical_office_title("US_SENATE", "DEM") == "UNITED STATES SENATOR (DEM PRIMARY)"
    assert canonical_office_title("US_SENATE", "REP") == "UNITED STATES SENATOR (REP PRIMARY)"


def test_canonical_office_title_omits_party_for_general():
    assert canonical_office_title("US_SENATE", "") == "UNITED STATES SENATOR"


@pytest.mark.parametrize("raw_name,expected", [
    ("Cory BOOKER", "CORY BOOKER"),
    ("Cory Booker", "CORY BOOKER"),
    ("DEM Cory BOOKER", "CORY BOOKER"),
])
def test_normalize_candidate_name_real_variants(raw_name, expected):
    assert normalize_candidate_name(raw_name) == expected


@pytest.mark.parametrize("raw_name", ["Write-in", "WRITE-IN", "Write-In", "Personal Choice"])
def test_normalize_candidate_name_returns_none_for_bookkeeping_rows(raw_name):
    assert normalize_candidate_name(raw_name) is None


@pytest.mark.parametrize("raw_name", [
    "",           # Empty string
    "   ",        # Whitespace-only
    "DEM",        # Bare party token with nothing else
])
def test_normalize_candidate_name_returns_none_for_empty_or_bare_party(raw_name):
    """Verify that empty strings and bare party tokens return None, not empty string."""
    assert normalize_candidate_name(raw_name) is None
