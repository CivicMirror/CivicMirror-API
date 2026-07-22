import os

from results.adapters.nm_parse import parse_election_wide_csv

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_election_wide_csv_extracts_all_rows():
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    assert len(rows) == 20


def test_parse_election_wide_csv_qualifies_colliding_office_titles():
    """Two different RaceIDs both named 'Mayor'/'MAYOR' must not collapse into
    one office_title — results/tasks.py::_bootstrap_races_from_results groups
    by (office_title, source_identity) and would otherwise merge candidates
    from unrelated cities into one Race."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)

    alamo_titles = {r.office_title for r in rows if r.raw["contest_code"] == "10083"}
    abq_titles = {r.office_title for r in rows if r.raw["contest_code"] == "10144"}

    assert alamo_titles == {"ALAMO CITY DISTRICT- ALL — Mayor"}
    assert abq_titles == {"CITY OF ALBUQUERQUE — MAYOR"}
    assert alamo_titles != abq_titles


def test_parse_election_wide_csv_matches_the_cross_referenced_test_contest():
    """RaceID 10087 / CandidateID 17700 is the contest cross-referenced
    throughout NM-Election_ResearchV4.md's crosswalk tables — 3,573 votes."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    overstreet = next(r for r in rows if r.raw["contest_code"] == "10087")

    assert overstreet.candidate_name == "DAVID MATTHEW OVERSTREET"
    assert overstreet.vote_count == 3573
    assert overstreet.vote_pct == 100.0
    assert overstreet.office_title == "ALAMO CITY DISTRICT- ALL — Municipal Judge"
    assert overstreet.jurisdiction_fragment == "ALAMO CITY DISTRICT- ALL"
    assert overstreet.result_type == "unofficial"
    assert overstreet.is_winner is None
    assert overstreet.is_write_in_aggregate is False


def test_parse_election_wide_csv_routes_yes_no_ids_to_option_label():
    """CandidateID 9001/9002 are generic, globally-reused Yes/No choice IDs —
    must route to option_label (a ballot-measure choice), never candidate_name."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)

    yes_rows = [r for r in rows if r.option_label == "Yes"]
    no_rows = [r for r in rows if r.option_label == "No"]
    assert len(yes_rows) == 2
    assert len(no_rows) == 2
    for row in yes_rows + no_rows:
        assert row.candidate_name is None

    dora_yes = next(r for r in yes_rows if r.raw["contest_code"] == "1188")
    assert dora_yes.vote_count == 63
    assert dora_yes.office_title == "DORA MUNICIPAL SCHOOL DISTRICT — Bond Question : Dora  General Obligation Bond Question"


def test_parse_election_wide_csv_falls_back_to_bare_race_name_when_area_num_blank():
    """RaceID 1255 has a blank AreaNum (county-level measure) — office_title
    should fall back to the bare RaceName rather than a dangling '— ' prefix."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    curry_yes = next(r for r in rows if r.raw["contest_code"] == "1255" and r.option_label == "Yes")

    assert curry_yes.office_title.startswith("COUNTY LOCAL OPTION GROSS RECEIPTS TAX QUESTION")
    assert " — " not in curry_yes.office_title[:5]
    assert curry_yes.jurisdiction_fragment == ""
    assert curry_yes.vote_count == 1987


def test_parse_election_wide_csv_passes_through_named_write_in_without_aggregation():
    """MO/MD each needed special write-in handling; NM doesn't — declared
    write-ins already appear as ordinary, individually-itemized rows with
    '(write in)' in the display name and a real vote count."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    write_in = next(r for r in rows if r.raw["contest_code"] == "10396")

    assert write_in.candidate_name == "MICHAEL CRAIG THOMPSON (write in)"
    assert write_in.vote_count == 159
    assert write_in.is_write_in_aggregate is False


def test_parse_election_wide_csv_handles_vote_for_multiple_races():
    """VoteFor=2 races (multi-seat) are parsed like any other — one ResultRow
    per candidate, no special-casing. (In the wider real Media.csv, races with
    more candidates than seats can have per-race percentages summing above
    100% — e.g. RaceID 10204, 10 candidates for 2 seats, sums to ~200% — but
    this fixture's example has exactly as many candidates as seats, so it
    sums to exactly 100%; the parser doesn't validate or enforce any
    particular sum either way, it just passes each row's percentage through.)"""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    councilor_rows = [r for r in rows if r.raw["contest_code"] == "10150"]

    assert len(councilor_rows) == 2
    assert {r.candidate_name for r in councilor_rows} == {"JAMES DEE WILEY", "YVONNE KAY MILLIGAN"}
    wiley = next(r for r in councilor_rows if r.candidate_name == "JAMES DEE WILEY")
    milligan = next(r for r in councilor_rows if r.candidate_name == "YVONNE KAY MILLIGAN")
    assert wiley.vote_count == 32
    assert milligan.vote_count == 56


def test_parse_election_wide_csv_sets_contest_code_and_party_code_in_raw():
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    overstreet = next(r for r in rows if r.raw["contest_code"] == "10087")
    assert overstreet.raw == {"contest_code": "10087", "party_code": ""}
