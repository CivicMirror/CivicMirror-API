import json
from pathlib import Path
from types import SimpleNamespace

from elections.models import Candidate, Election, Race
from integrations.ga_sos.mappers import (
    _get_text,
    map_candidate,
    map_election,
    map_measure_option,
    map_race,
    normalize_office_title,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_get_text_returns_requested_language_or_first_entry():
    names = [
        {"languageId": "es", "text": "Senador"},
        {"languageId": "en", "text": "Senator"},
    ]

    assert _get_text(names) == "Senator"
    assert _get_text([{"languageId": "es", "text": "Senador"}]) == "Senador"
    assert _get_text([]) == ""


def test_map_election_preserves_opaque_public_id():
    row = next(
        e for e in _fixture("jurisdiction_georgia.json")["elections"]
        if e["publicElectionId"] == "06162026GeneralPrimaryRunoff"
    )

    mapped = map_election(row)

    assert mapped["source_id"] == "ga_sos:06162026GeneralPrimaryRunoff"
    assert mapped["state"] == "GA"
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["election_type"] == Election.ElectionType.PRIMARY_RUNOFF
    assert mapped["source_metadata"]["enr_slug"] == "06162026GeneralPrimaryRunoff"
    assert mapped["source_metadata"]["ga_public_election_id"] == "06162026GeneralPrimaryRunoff"


def test_normalize_office_title_removes_agreeing_primary_suffix_only():
    assert normalize_office_title("US Senate - Rep", "REP") == "us senate"
    assert normalize_office_title("Secretary of State - Dem", "DEM") == "secretary of state"
    assert normalize_office_title("Governor - Rep", "DEM") == "governor rep"
    assert normalize_office_title("Special State Senate - District 7", "") == (
        "special state senate district 7"
    )


def test_map_race_uses_ga_source_and_ballot_item_id():
    data = _fixture("election_data_06162026.json")
    item = next(b for b in data["ballotItems"] if _get_text(b["name"]) == "US Senate - Rep")
    election = SimpleNamespace(
        status=Election.Status.RESULTS_PENDING,
        source_id="ga_sos:06162026GeneralPrimaryRunoff",
        source_metadata={
            "enr_slug": "06162026GeneralPrimaryRunoff",
            "ga_public_election_id": "06162026GeneralPrimaryRunoff",
        },
    )

    mapped = map_race(election, item)

    assert mapped["source"] == Race.Source.GA_SOS
    assert mapped["office_title"] == "US Senate - Rep"
    assert mapped["normalized_office_title"] == "us senate"
    assert mapped["geography_scope"] == "federal"
    assert mapped["jurisdiction"] == "Georgia"
    assert mapped["source_metadata"]["ga_ballot_item_id"] == item["id"]
    assert mapped["source_metadata"]["enr_slug"] == "06162026GeneralPrimaryRunoff"
    assert mapped["source_metadata"]["party_name"] == "REP"
    assert mapped["source_metadata"]["reporting_units"] == 159
    assert mapped["source_metadata"]["total_units"] == 159


def test_map_race_identifies_district_scope():
    data = _fixture("election_data_06162026.json")
    item = next(b for b in data["ballotItems"] if "State Senate - District 7" in _get_text(b["name"]))
    election = SimpleNamespace(
        status=Election.Status.UPCOMING,
        source_id="ga_sos:06162026GeneralPrimaryRunoff",
        source_metadata={"enr_slug": "06162026GeneralPrimaryRunoff"},
    )

    mapped = map_race(election, item)

    assert mapped["geography_scope"] == "district"
    assert mapped["jurisdiction"] == "District 7"
    assert mapped["certification_status"] == Race.CertificationStatus.UPCOMING


def test_map_candidate_reads_party_from_enhanced_voting_api_shape():
    item = _fixture("election_data_06162026.json")["ballotItems"][0]
    option = item["summaryResults"]["ballotOptions"][0]

    mapped = map_candidate(option)

    assert mapped["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert mapped["party"] == "REP"
    assert mapped["source_metadata"]["ga_native_id"] == option.get("nativeId")
    assert mapped["source_metadata"]["party_abbreviation"] == "REP"
    assert mapped["source_metadata"]["is_write_in"] is False


def test_map_candidate_reads_party_from_media_export_shape():
    item = _fixture("media_export_sample_06162026.json")["results"]["ballotItems"][0]
    option = item["ballotOptions"][0]

    mapped = map_candidate(option)

    assert mapped["party"] == "REP"
    assert mapped["source_metadata"]["party_abbreviation"] == "REP"
    assert mapped["source_metadata"]["ga_native_id"] == option.get("id")


def test_map_measure_option_preserves_label():
    mapped = map_measure_option({"name": [{"languageId": "en", "text": "Yes"}], "nativeId": "yes-1"})

    assert mapped["option_label"] == "Yes"
    assert mapped["source_metadata"]["ga_native_id"] == "yes-1"
