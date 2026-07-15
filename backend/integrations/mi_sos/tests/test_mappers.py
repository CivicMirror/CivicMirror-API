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
