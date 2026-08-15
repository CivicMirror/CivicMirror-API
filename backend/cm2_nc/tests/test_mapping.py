from datetime import date

import pytest

from cm2_ingestion.contracts import ContractValidationError, ElectionRecord
from cm2_nc.mapping.identity import contest_public_id, stable_public_id
from cm2_nc.mapping.jurisdictions import map_jurisdiction
from cm2_nc.mapping.measures import is_measure_contest
from cm2_nc.mapping.offices import map_office
from cm2_nc.mapping.results import (
    build_post_election_batch,
    classify_choice,
    normalized_choice_label,
    split_contest_label,
)
from cm2_nc.source_records import NcResultRow


@pytest.mark.parametrize(
    "contest_name",
    [
        "County Bond",
        "County Bonds",
        "Local Referendum",
        "Local Referenda",
        "Constitutional Amendment",
        "Ballot Measure",
        "Proposition 1",
        "School Question",
        "Citizen Initiative",
        "Tax Levy",
        "Noise Ordinance",
        "County Resolution",
    ],
)
def test_measure_filter_matches_only_approved_whole_contest_words(contest_name):
    assert is_measure_contest(contest_name) is True


@pytest.mark.parametrize(
    "contest_name",
    [
        "COUNTY BONDSMAN",
        "INITIATIVELY ELECTED DIRECTOR",
        "QUESTIONER COUNTY COMMISSIONER",
        "RESOLUTIONIST MAYOR",
    ],
)
def test_measure_filter_does_not_match_substrings(contest_name):
    assert is_measure_contest(contest_name) is False


def test_measure_filter_never_examines_candidate_name():
    contest_name = "US SENATE"
    candidate_name = "Jordan Resolution"

    assert is_measure_contest(contest_name) is False
    assert "resolution" in candidate_name.casefold()


def test_stable_public_id_normalizes_case_and_space_but_retains_collision_digest():
    first = stable_public_id("office", " City   of Raleigh ", "Mayor")
    same = stable_public_id("office", "city of raleigh", "mayor")
    different = stable_public_id("office", "Town of Raleigh", "Mayor")

    assert first == same
    assert first != different
    assert first.startswith("nc/office/city-of-raleigh/mayor/")
    assert len(first.rsplit("/", 1)[-1]) == 16


@pytest.mark.parametrize(
    ("contest_name", "county_name", "classification", "name"),
    [
        ("US SENATE", "WAKE", "state", "North Carolina"),
        (
            "US HOUSE OF REPRESENTATIVES DISTRICT 09",
            "HOKE",
            "congressional_district",
            "North Carolina Congressional District 09",
        ),
        (
            "NC STATE SENATE DISTRICT 01",
            "WAKE",
            "state_legislative_district",
            "North Carolina State Senate District 01",
        ),
        (
            "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 01",
            "WAKE",
            "judicial_district",
            "North Carolina Judicial District 01",
        ),
        ("WAKE COUNTY SHERIFF", "WAKE", "county", "Wake County"),
        (
            "ALAMANCE-BURLINGTON BOARD OF EDUCATION",
            "ALAMANCE",
            "school_district",
            "Alamance-Burlington School District",
        ),
        ("CITY OF RALEIGH MAYOR", "WAKE", "municipality", "City of Raleigh"),
        (
            "ALAMANCE SOIL AND WATER CONSERVATION DISTRICT SUPERVISOR",
            "ALAMANCE",
            "other",
            "Alamance Soil and Water Conservation District",
        ),
        (
            "FIRST CRAVEN SANITARY DISTRICT BOARD MEMBER",
            "CRAVEN",
            "other",
            "First Craven Sanitary District",
        ),
        ("MOSQUITO CONTROL BOARD MEMBER", "WAKE", "county", "Wake County"),
    ],
)
def test_jurisdiction_mapping_covers_people_based_nc_scopes(
    contest_name,
    county_name,
    classification,
    name,
):
    records = map_jurisdiction(contest_name, county_name)
    jurisdiction = records[-1]

    assert records[0].name == "North Carolina"
    assert records[0].classification == "state"
    assert jurisdiction.classification == classification
    assert jurisdiction.name == name
    if classification != "state":
        assert jurisdiction.parent_public_id == records[0].public_id


def test_office_mapping_preserves_judicial_seats_and_strips_only_unexpired_marker():
    jurisdiction = map_jurisdiction(
        "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 01",
        "WAKE",
    )[-1]
    seat_one = map_office(
        "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 01",
        jurisdiction,
        term_years=4,
        vote_for=1,
    )
    seat_two = map_office(
        "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 02",
        jurisdiction,
        term_years=4,
        vote_for=1,
    )
    unexpired = map_office(
        "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 01 (UNEXPIRED)",
        jurisdiction,
        term_years=4,
        vote_for=1,
    )

    assert seat_one.canonical_name == "District Court Judge Seat 01"
    assert seat_one.role == "judge"
    assert seat_one.default_term_months == 48
    assert seat_one.positions == 1
    assert seat_one.public_id != seat_two.public_id
    assert seat_one.public_id == unexpired.public_id


def test_us_house_office_is_permanent_with_district_on_jurisdiction():
    jurisdiction = map_jurisdiction("US HOUSE OF REPRESENTATIVES DISTRICT 09", "HOKE")[-1]

    office = map_office(
        "US HOUSE OF REPRESENTATIVES DISTRICT 09",
        jurisdiction,
        term_years=2,
        vote_for=1,
    )

    assert office.canonical_name == "U.S. Representative"
    assert office.role == "representative"
    assert office.default_term_months == 24


def test_multiple_offices_share_one_identical_jurisdiction_record():
    school_district_two = map_jurisdiction(
        "ALEXANDER COUNTY BOARD OF EDUCATION DISTRICT 02",
        "ALEXANDER",
    )[-1]
    school_district_three = map_jurisdiction(
        "ALEXANDER COUNTY BOARD OF EDUCATION DISTRICT 03",
        "ALEXANDER",
    )[-1]
    city_council = map_jurisdiction("CITY OF ASHEVILLE CITY COUNCIL", "BUNCOMBE")[-1]
    city_mayor = map_jurisdiction("CITY OF ASHEVILLE MAYOR", "BUNCOMBE")[-1]

    assert school_district_two == school_district_three
    assert city_council == city_mayor


def test_contest_public_id_matches_manual_construction():
    key_a = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="REP",
        is_unexpired=False,
    )
    key_b = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="REP",
        is_unexpired=False,
    )
    key_different_party = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="DEM",
        is_unexpired=False,
    )
    assert key_a == key_b
    assert key_a != key_different_party


def test_map_office_without_term_years_leaves_default_term_null():
    jurisdiction = map_jurisdiction("US SENATE (REP)".replace(" (REP)", ""), "")[-1]
    office = map_office("US SENATE", jurisdiction, vote_for=1)
    assert office.default_term_months is None


def test_split_contest_label_extracts_party_only():
    base, party, is_unexpired = split_contest_label("US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)")
    assert base == "US HOUSE OF REPRESENTATIVES DISTRICT 11"
    assert party == "REP"
    assert is_unexpired is False


def test_split_contest_label_extracts_unexpired_only():
    base, party, is_unexpired = split_contest_label("GATES COUNTY BOARD OF EDUCATION DISTRICT 02 (UNEXPIRED)")
    assert base == "GATES COUNTY BOARD OF EDUCATION DISTRICT 02"
    assert party == ""
    assert is_unexpired is True


def test_split_contest_label_extracts_unexpired_and_party_in_order():
    base, party, is_unexpired = split_contest_label(
        "PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)"
    )
    assert base == "PERSON COUNTY BOARD OF COMMISSIONERS"
    assert party == "REP"
    assert is_unexpired is True


def test_split_contest_label_with_no_suffix():
    base, party, is_unexpired = split_contest_label("CITY OF ASHEVILLE CITY COUNCIL")
    assert base == "CITY OF ASHEVILLE CITY COUNCIL"
    assert party == ""
    assert is_unexpired is False


def test_classify_choice_ordinary_candidate():
    assert classify_choice("Chuck Edwards") == "candidate"


def test_classify_choice_named_write_in():
    assert classify_choice("Jamie Ager (Write-In)") == "named_write_in"


def test_classify_choice_anonymous_write_in_both_spellings():
    assert classify_choice("Write-In (Miscellaneous)") == "write_in_aggregate"
    assert classify_choice("Miscellaneous (Write-In)") == "write_in_aggregate"
    assert classify_choice("MIscellaneous (Write-In)") == "write_in_aggregate"


def test_normalized_choice_label_strips_write_in_marker():
    assert normalized_choice_label("Jamie Ager (Write-In)", "named_write_in") == "jamie ager"
    assert normalized_choice_label("Chuck Edwards", "candidate") == "chuck edwards"
    assert normalized_choice_label("Write-In (Miscellaneous)", "write_in_aggregate") == "write-in"


def _result_row(**overrides) -> NcResultRow:
    values = {
        "row_number": 2,
        "county_name": "BUNCOMBE",
        "election_date": date(2026, 3, 3),
        "precinct": "19.1",
        "contest_type": "S",
        "contest_name": "US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)",
        "choice": "Chuck Edwards",
        "choice_party": "REP",
        "vote_for": 1,
        "total_votes": 33,
        "is_real_precinct": True,
    }
    values.update(overrides)
    return NcResultRow(**values)


def _primary_election() -> ElectionRecord:
    return ElectionRecord(
        public_id="nc/election/2026-03-03/primary",
        name="2026 North Carolina Primary",
        election_date=date(2026, 3, 3),
        election_type="primary",
        lifecycle_status="active",
        source_key="2026-03-03-primary",
    )


def test_build_post_election_batch_matches_existing_election_and_produces_observation():
    batch = build_post_election_batch((_result_row(),), existing_elections=(_primary_election(),))
    assert batch.state == "NC"
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert observation.choice_type == "candidate"
    assert observation.choice_party == "REP"
    assert observation.vote_total == 33
    contest = batch.new_contests[0]
    assert contest.election_public_id == "nc/election/2026-03-03/primary"
    assert contest.party_contest == "REP"
    assert contest.is_partisan is True


def test_build_post_election_batch_reuses_contest_public_id_formula_across_precincts():
    row_a = _result_row(precinct="19.1", total_votes=33)
    row_b = _result_row(precinct="20.1", total_votes=20)
    batch = build_post_election_batch((row_a, row_b), existing_elections=(_primary_election(),))
    contest_ids = {contest.public_id for contest in batch.new_contests}
    assert len(contest_ids) == 1
    assert len({observation.contest_public_id for observation in batch.observations}) == 1


def test_build_post_election_batch_excludes_measures_with_notice():
    row = _result_row(
        contest_name="CITY OF HENDERSONVILLE TRANSPORTATION BONDS REFERENDUM",
        contest_type="C",
        choice="FOR",
        choice_party="",
        vote_for=1,
    )
    batch = build_post_election_batch((row,), existing_elections=(_primary_election(),))
    assert batch.observations == ()
    assert batch.notices[0].code == "measure_excluded"


def test_build_post_election_batch_classifies_write_ins():
    named = _result_row(
        row_number=3,
        choice="Jamie Ager (Write-In)",
        choice_party="DEM",
        total_votes=2,
    )
    aggregate = _result_row(
        row_number=4,
        precinct="1.1",
        contest_name="PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)",
        contest_type="C",
        choice="Write-In (Miscellaneous)",
        choice_party="",
        county_name="PERSON",
        total_votes=1,
    )
    batch = build_post_election_batch((named, aggregate), existing_elections=(_primary_election(),))
    by_type = {observation.choice_type for observation in batch.observations}
    assert by_type == {"named_write_in", "write_in_aggregate"}


def test_build_post_election_batch_raises_when_no_election_matches_date():
    with pytest.raises(ContractValidationError):
        build_post_election_batch((_result_row(),), existing_elections=())


def test_build_post_election_batch_disambiguates_by_party_presence():
    general = ElectionRecord(
        public_id="nc/election/2026-03-03/general",
        name="General",
        election_date=date(2026, 3, 3),
        election_type="general",
        lifecycle_status="active",
        source_key="2026-03-03-general",
    )
    batch = build_post_election_batch(
        (_result_row(),),
        existing_elections=(general, _primary_election()),
    )
    assert batch.new_contests[0].election_public_id == "nc/election/2026-03-03/primary"
