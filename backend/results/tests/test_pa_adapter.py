"""Unit tests for the Pennsylvania electionreturns.pa.gov results adapter."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from results.adapters.pa import PennsylvaniaAdapter, _build_report_payload, _parse_report_csv

SAMPLE_CSV = (
    '"Election Name","County Name","Office Name","District Name","Party Name","Candidate Name",'
    '"Votes","Yes Votes","No Votes","Election Day Votes","ElectionDay Yes Votes","Election Day No Votes",'
    '"Mail Votes","Mail Yes Votes","Mail No Votes","Provisional Votes","Provisional Yes Votes","Provisional No Votes"\n'
    '"2026 General Primary","ADAMS","Governor","Statewide","Democratic","JOSH SHAPIRO",'
    '"6,223","0","0","2,636","0","0","3,579","0","0","8","0","0"\n'
    '"2026 General Primary","ADAMS","Lieutenant Governor","Statewide","Republican","JASON RICHEY",'
    '"6,086","0","0","4,723","0","0","1,358","0","0","5","0","0"\n'
    '"2026 General Primary","ADAMS","Representative in Congress","13th Congressional District","Republican","JOHN JOYCE",'
    '"9,388","0","0","7,242","0","0","2,141","0","0","5","0","0"\n'
    '"2026 General Primary","YORK","Representative in the General Assembly","55th Legislative District","Republican","JANE DOE",'
    '"10","0","0","7","0","0","2","0","0","1","0","0"\n'
    '"2026 General Primary","YORK","Question","Statewide","","Question Option",'
    '"0","11","3","0","7","2","0","3","1","0","1","0"\n'
)


FILTER_DATA = {
    "Table": [
        {"OfficeID": 3},
        {"OfficeID": 4},
    ],
    "Table1": [
        {"PartyID": 3},
        {"PartyID": 4},
    ],
    "Table2": [
        {"CandidateID": 23048},
        {"CandidateID": 23049},
    ],
}


def test_pa_adapter_registered():
    import results.adapters.pa  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "PA" in list_supported_states()
    assert get_adapter("PA") is PennsylvaniaAdapter


def test_parse_report_csv_normalizes_races_and_vote_modes():
    rows = _parse_report_csv(SAMPLE_CSV)

    adams_governor = next(
        row for row in rows
        if row.office_title == "Governor"
        and row.candidate_name == "JOSH SHAPIRO"
        and row.jurisdiction_fragment == "ADAMS"
    )
    assert adams_governor.vote_count == 6223
    assert adams_governor.result_type == "official"
    assert adams_governor.raw["party"] == "Democratic"
    assert adams_governor.raw["election_day_votes"] == 2636
    assert adams_governor.raw["mail_votes"] == 3579
    assert adams_governor.raw["provisional_votes"] == 8

    assert any(row.office_title == "Lieutenant Governor" for row in rows)
    assert any(row.office_title == "U.S. House - District 13" for row in rows)
    assert any(row.office_title == "State House - District 55" for row in rows)


def test_parse_report_csv_adds_statewide_aggregate_rows():
    rows = _parse_report_csv(SAMPLE_CSV)

    statewide = next(
        row for row in rows
        if row.office_title == "Governor"
        and row.candidate_name == "JOSH SHAPIRO"
        and row.jurisdiction_fragment == ""
    )
    assert statewide.vote_count == 6223
    assert statewide.raw["pa_aggregate"] == "statewide"


def test_parse_report_csv_yes_no_votes_as_measure_options():
    rows = _parse_report_csv(SAMPLE_CSV)

    yes = next(row for row in rows if row.office_title == "Question" and row.option_label == "Yes")
    no = next(row for row in rows if row.office_title == "Question" and row.option_label == "No")

    assert yes.candidate_name is None
    assert yes.vote_count == 11
    assert yes.raw["election_day_votes"] == 7
    assert no.vote_count == 3
    assert no.raw["mail_votes"] == 1


def test_build_report_payload_uses_all_ids_from_filter_data():
    payload = _build_report_payload(117, "P", FILTER_DATA)

    assert payload["ElectionID"] == 117
    assert payload["ElectionsubType"] == "P"
    assert payload["OfficeIds"] == [3, 4]
    assert payload["PartyIds"] == [3, 4]
    assert payload["CandidateIds"] == [23048, 23049]
    assert payload["CountyIds"] == []
    assert payload["ReportType"] == "D"
    assert payload["ExportType"] == "C"


@patch("results.adapters.pa.cache")
@patch("results.adapters.pa.PaElectionReturnsClient")
def test_fetch_results_resolves_election_from_registry_when_metadata_missing(mock_client_cls, mock_cache):
    adapter = PennsylvaniaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}
    mock_election.election_type = "primary"
    mock_election.election_date = date(2026, 5, 19)
    mock_cache.get.return_value = None

    client = mock_client_cls.return_value.__enter__.return_value
    client.get_election_list.return_value = [
        {
            "Electionid": 117,
            "ElectionType": "P",
            "ElectionDate": "05/19/2026",
            "IsActive": 1,
            "ElectionName": "2026 General Primary",
        }
    ]
    client.get_filter_data.return_value = FILTER_DATA
    client.generate_report.return_value = SAMPLE_CSV

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 5, 19), election_id=1)

    assert result.mapping_confidence == "full"
    assert len(result.rows) > 0
    client.get_election_list.assert_called_once()


@patch("results.adapters.pa.cache")
@patch("results.adapters.pa.PaElectionReturnsClient")
def test_fetch_results_posts_generate_report_and_parses_csv(mock_client_cls, mock_cache):
    adapter = PennsylvaniaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {
        "pa_election_id": 117,
        "pa_election_subtype": "P",
        "pa_is_active": 1,
    }
    mock_cache.get.return_value = None

    client = mock_client_cls.return_value.__enter__.return_value
    client.get_filter_data.return_value = FILTER_DATA
    client.generate_report.return_value = SAMPLE_CSV

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 5, 19), election_id=44)

    assert result.mapping_confidence == "full"
    assert len(result.rows) > 0
    assert result.source_version
    client.warm_session.assert_called_once()
    client.get_filter_data.assert_called_once_with(117, "P")
    client.generate_report.assert_called_once()


@patch("results.adapters.pa.cache")
@patch("results.adapters.pa.PaElectionReturnsClient")
def test_fetch_results_unchanged_when_report_hash_matches_cache(mock_client_cls, mock_cache):
    adapter = PennsylvaniaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {
        "pa_election_id": 117,
        "pa_election_subtype": "P",
    }

    client = mock_client_cls.return_value.__enter__.return_value
    client.get_filter_data.return_value = FILTER_DATA
    client.generate_report.return_value = SAMPLE_CSV

    import hashlib

    mock_cache.get.return_value = hashlib.sha256(SAMPLE_CSV.encode("utf-8")).hexdigest()

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 5, 19), election_id=44)

    assert result.unchanged is True
    assert result.rows == []
