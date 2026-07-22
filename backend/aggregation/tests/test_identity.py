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
    assert normalize_office_title("  GOVERNOR  ") == "governor"


def test_normalize_office_title_strips_geographic_qualifiers():
    # CA SOS appends " - Statewide Results"; civic_api sends the bare office.
    assert normalize_office_title("Governor - Statewide Results") == "governor"
    assert normalize_office_title("  Governor   - Statewide  ") == "governor"
    assert normalize_office_title("GOVERNOR") == "governor"


def test_normalize_office_title_preserves_district_number():
    # District numbers are discriminators, not geographic qualifiers.
    assert (
        normalize_office_title("U.S. Representative District 1 - Statewide Results")
        == "u.s. representative district 1"
    )


def test_normalize_office_title_keeps_local_qualifier_for_measures():
    # A city Measure A and a county Measure A in one election must stay distinct.
    assert (
        normalize_office_title("Measure A - Citywide", race_type="measure")
        == "measure a - citywide"
    )
    assert (
        normalize_office_title("Measure A - Countywide", race_type="measure")
        == "measure a - countywide"
    )
    # Statewide is still stripped for measures (one such contest per election).
    assert (
        normalize_office_title("Proposition 1 - Statewide", race_type="measure")
        == "proposition 1"
    )
    # Candidate races strip local qualifiers too.
    assert (
        normalize_office_title("City Council - Citywide", race_type="candidate")
        == "city council"
    )


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


def test_normalize_party_strips_ca_party_preference_prefix():
    # CA SOS sends "Party Preference: Democratic"; it must collapse to the same
    # code as another source's terse "Dem" so candidates match, not duplicate.
    assert normalize_party("Party Preference: Democratic") == "DEM"
    assert normalize_party("Party Preference: Republican") == "REP"
    assert normalize_party("Party Preference: Democratic") == normalize_party("Dem")
    # Unknown party after stripping keeps the cleaned label, not the prefix.
    assert normalize_party("Party Preference: Whig") == "WHIG"


def test_normalize_party_aligns_civic_and_ca_sos_vocab():
    # No-party-preference: civic "NPP" vs CA "Party Preference: None".
    assert normalize_party("NPP") == normalize_party("Party Preference: None") == "NP"
    # Peace & Freedom: civic "P&F" vs CA "Party Preference: Peace and Freedom".
    assert normalize_party("P&F") == normalize_party("Party Preference: Peace and Freedom") == "PF"


def test_race_canonical_key_combines_election_key_office_ocd_type():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "ocd-division/country:us/state:ca", "candidate")
    assert key == f"{ek}|governor|ocd-division/country:us/state:ca|candidate"


def test_race_canonical_key_uses_no_ocd_placeholder_when_blank():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "", "candidate")
    assert key == f"{ek}|governor|NO_OCD|candidate"


def test_race_canonical_key_collapses_bare_state_code_to_no_ocd():
    # civic_api falls back to election.state ("CA"); ca_sos emits "". Both must
    # collapse to NO_OCD so the two sources key-match.
    ek = "CA:primary:2026-06-02:state"
    assert race_canonical_key(ek, "Governor", "CA", "candidate") == (
        f"{ek}|governor|NO_OCD|candidate"
    )
    assert race_canonical_key(ek, "Governor", " ca ", "candidate") == (
        f"{ek}|governor|NO_OCD|candidate"
    )


def test_race_canonical_key_merges_cross_source_governor():
    # The original duplicate: civic_api "GOVERNOR"+"CA" vs
    # ca_sos "Governor - Statewide Results"+"". Both fixes together collide.
    ek = "CA:primary:2026-06-02:state"
    civic = race_canonical_key(ek, "GOVERNOR", "CA", "candidate")
    ca_sos = race_canonical_key(ek, "Governor - Statewide Results", "", "candidate")
    assert civic == ca_sos == f"{ek}|governor|NO_OCD|candidate"


def test_race_canonical_key_preserves_full_ocd_division_id():
    ek = "CA:primary:2026-06-02:state"
    ocd = "ocd-division/country:us/state:ca/cd:1"
    key = race_canonical_key(ek, "U.S. Representative District 1", ocd, "candidate")
    assert key == f"{ek}|u.s. representative district 1|{ocd}|candidate"


def test_race_canonical_key_omitted_variant_matches_pre_existing_key():
    """Default behavior (no contest_variant) must be byte-identical to the
    pre-extension key, so existing sources are unaffected."""
    ek = "CA:primary:2026-06-02:state"
    assert (
        race_canonical_key(ek, "Governor", "", "candidate")
        == race_canonical_key(ek, "Governor", "", "candidate", "")
        == f"{ek}|governor|NO_OCD|candidate"
    )


def test_race_canonical_key_variant_appended_when_present():
    ek = "VT:primary:2026-08-11:state"
    key = race_canonical_key(ek, "Governor", "", "candidate", "vt:statewide:D:1:statewide")
    assert key == f"{ek}|governor|NO_OCD|candidate|vt:statewide:d:1:statewide"


def test_race_canonical_key_variant_disambiguates_primary_parties():
    """The bug this fix exists for: VT publishes Democratic, Progressive, and
    Republican REPRESENTATIVE TO CONGRESS as three separate contests sharing
    the same office ID (oid=4). Without contest_variant, all three would
    collapse into one Race; with it, they stay distinct."""
    ek = "VT:primary:2026-08-11:state"
    dem = race_canonical_key(ek, "Representative to Congress", "", "candidate", "vt:federal:D:4:statewide")
    prog = race_canonical_key(ek, "Representative to Congress", "", "candidate", "vt:federal:PR:4:statewide")
    rep = race_canonical_key(ek, "Representative to Congress", "", "candidate", "vt:federal:R:4:statewide")
    assert len({dem, prog, rep}) == 3


def test_race_canonical_key_variant_is_case_and_whitespace_normalized():
    ek = "VT:primary:2026-08-11:state"
    a = race_canonical_key(ek, "Governor", "", "candidate", "VT:Statewide:D:1:Statewide")
    b = race_canonical_key(ek, "Governor", "", "candidate", "  vt:statewide:d:1:statewide  ")
    assert a == b


def test_race_canonical_key_blank_variant_after_normalization_is_omitted():
    ek = "CA:primary:2026-06-02:state"
    key = race_canonical_key(ek, "Governor", "", "candidate", "   ")
    assert key == f"{ek}|governor|NO_OCD|candidate"
