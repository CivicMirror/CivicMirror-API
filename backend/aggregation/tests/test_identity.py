from datetime import date

from aggregation.identity import (
    election_canonical_key,
    name_match_key,
    normalize_name,
    normalize_office_title,
    normalize_party,
    race_canonical_key,
)


def test_election_canonical_key_is_source_independent():
    key = election_canonical_key("CA", "primary", date(2026, 6, 2), "state")
    assert key == "CA:primary:2026-06-02:state"


def test_normalize_office_title_collapses_whitespace_and_case():
    assert normalize_office_title("  Governor   - Statewide  ") == "governor - statewide"


def test_normalize_name_strips_punctuation_and_lowercases():
    assert normalize_name("Xavier Becerra") == "xavier becerra"
    assert normalize_name("Becerra, Xavier") == "becerra xavier"
    assert normalize_name("Robert F. Kennedy Jr.") == "robert f kennedy jr"


def test_name_match_key_is_order_independent():
    # "Last, First" and "First Last" must produce the same match key.
    assert name_match_key("Xavier Becerra") == name_match_key("Becerra, Xavier")
    assert name_match_key("Robert F. Kennedy Jr.") == name_match_key("kennedy robert jr f")


def test_normalize_party_maps_variants_to_codes():
    assert normalize_party("Democratic Party") == "DEM"
    assert normalize_party("Dem") == "DEM"
    assert normalize_party("DEM") == "DEM"
    assert normalize_party("Republican") == "REP"
    assert normalize_party("") == ""
    assert normalize_party("Green") == "GRN"
    assert normalize_party("Some Unknown Party") == "SOME UNKNOWN PARTY"


def test_race_canonical_key_combines_election_key_office_ocd_type():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "ocd-division/country:us/state:ca", "candidate")
    assert key == f"{ek}|governor|ocd-division/country:us/state:ca|candidate"


def test_race_canonical_key_uses_no_ocd_placeholder_when_blank():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "", "candidate")
    assert key == f"{ek}|governor|NO_OCD|candidate"
