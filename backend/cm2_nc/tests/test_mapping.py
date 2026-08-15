import pytest

from cm2_nc.mapping.identity import stable_public_id
from cm2_nc.mapping.jurisdictions import map_jurisdiction
from cm2_nc.mapping.measures import is_measure_contest
from cm2_nc.mapping.offices import map_office


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
