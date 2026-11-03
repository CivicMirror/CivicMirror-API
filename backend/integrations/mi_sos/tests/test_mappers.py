from elections.models import Candidate
from integrations.mi_sos.mappers import (
    candidate_status,
    is_write_in,
    normalize_office_title,
    party_abbrev,
    result_office_title,
)


def test_normalize_office_title_handles_state_and_district_offices():
    assert normalize_office_title("GOVERNOR 4 Year Term (1) Position") == "Governor"
    assert normalize_office_title("UNITED STATES REPRESENTATIVE 7th District") == "U.S. House - District 7"
    assert normalize_office_title("STATE REPRESENTATIVE 55th District") == "State House - District 55"
    assert normalize_office_title("35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027") == (
        "State Senate - District 35"
    )


def test_candidate_status_maps_withdrawn_and_disqualified():
    assert candidate_status("") == Candidate.CandidateStatus.RUNNING
    assert candidate_status("WITHD") == Candidate.CandidateStatus.WITHDRAWN
    assert candidate_status("DISQ") == Candidate.CandidateStatus.DISQUALIFIED


def test_party_abbrev_maps_common_michigan_parties():
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Libertarian") == "LIB"


def test_result_helpers_delegate_to_normalization_and_write_in_detection():
    assert result_office_title("35TH DISTRICT STATE SENATOR") == "State Senate - District 35"
    assert is_write_in("WRITE-IN") is True
    assert is_write_in("GREENE, CHEDRICK") is False


# ---------------------------------------------------------------------------
# The general listing words offices and parties differently from the primary
# ---------------------------------------------------------------------------

def test_general_listing_office_wordings_normalize_to_the_primary_titles():
    """Both listings must produce one title, because results go through the same path."""
    assert normalize_office_title("U.S. Senate 6 Year Term (1) Position") == "U.S. Senate"
    assert normalize_office_title("UNITED STATES SENATOR") == "U.S. Senate"
    assert normalize_office_title(
        "1st District Representative in Congress 2 Year Term (1) Position"
    ) == "U.S. House - District 1"
    assert normalize_office_title(
        "12th District Representative in State Legislature 2 Year Term (1) Position Files In WAYNE County"
    ) == "State House - District 12"
    assert normalize_office_title("Governor / Lt. Governor 4 Year Term (1) Position") == "Governor"
    assert normalize_office_title("Secretary of State 4 Year Term (1) Position") == "Secretary of State"
    assert normalize_office_title("Attorney General 4 Year Term (1) Position") == "Attorney General"


def test_university_board_seats_do_not_collapse_into_the_governors_race():
    """"Governor of Wayne State University" is a university board seat.

    A bare "GOVERNOR" substring test put its candidates on Michigan's gubernatorial
    ballot alongside the real nominees.
    """
    assert normalize_office_title(
        "Governor of Wayne State University 8 Year Terms (2) Positions"
    ) == "Governor of Wayne State University"
    assert normalize_office_title("Governor / Lt. Governor 4 Year Term (1) Position") == "Governor"
    assert normalize_office_title(
        "Member of the State Board of Education 8 Year Terms (2) Positions"
    ) == "State Board of Education"
    assert normalize_office_title(
        "Regent of the University of Michigan 8 Year Terms (2) Positions"
    ) == "Regent of the University of Michigan"
    assert normalize_office_title(
        "Trustee of Michigan State University 8 Year Terms (2) Positions"
    ) == "Trustee of Michigan State University"


def test_party_abbrev_handles_the_party_suffix_and_every_michigan_party():
    """The general listing says "Democratic Party"; the primary says "Democratic"."""
    assert party_abbrev("Democratic Party") == "DEM"
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Republican Party") == "REP"
    assert party_abbrev("Libertarian Party") == "LIB"
    # Truncating the unmapped label gave "GRE", "U.S", "WOR" and "NAT" instead.
    assert party_abbrev("Green Party") == "GRN"
    assert party_abbrev("U.S. Taxpayers Party") == "UST"
    assert party_abbrev("Working Class Party") == "WCP"
    assert party_abbrev("Natural Law Party") == "NLP"
    assert party_abbrev("No Party Affiliation") == "NPA"


def test_incumbent_marker_is_never_treated_as_a_party():
    assert party_abbrev("INCUMBENT") == ""
    assert party_abbrev("Incumbent") == ""


def test_michigan_elects_its_education_and_university_boards_statewide():
    from integrations.mi_sos.mappers import geography_scope

    assert geography_scope("State Board of Education") == "statewide"
    assert geography_scope("Regent of the University of Michigan") == "statewide"
    assert geography_scope("Trustee of Michigan State University") == "statewide"
    assert geography_scope("Governor of Wayne State University") == "statewide"
    # Everything else still comes from the shared inferrer.
    assert geography_scope("Governor") == "statewide"
    assert geography_scope("U.S. Senate") == "federal"
    assert geography_scope("State House - District 1") == "district"


def test_result_contest_titles_match_the_races_the_listing_creates():
    """MVIC results name contests in the primary listing's wording, in caps.

    The 705 fixture shows the format: "35TH DISTRICT STATE SENATOR PARTIAL TERM
    ENDING 1/1/2027". A prefixed contest name must still match, which is why the
    governorship is matched by containment and not by a prefix test.
    """
    assert result_office_title("GOVERNOR") == "Governor"
    assert result_office_title("GOVERNOR / LT. GOVERNOR") == "Governor"
    assert result_office_title("STATE OF MICHIGAN - GOVERNOR") == "Governor"
    assert result_office_title("UNITED STATES SENATOR") == "U.S. Senate"
    assert result_office_title("35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027") == (
        "State Senate - District 35"
    )
    # ... and the board seats stay out of the gubernatorial race.
    assert result_office_title("GOVERNOR OF WAYNE STATE UNIVERSITY") == (
        "Governor of Wayne State University"
    )
    assert result_office_title("MEMBER OF THE BOARD OF GOVERNORS OF WAYNE STATE UNIVERSITY") != "Governor"
