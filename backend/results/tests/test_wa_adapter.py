"""
Unit tests for the Washington results adapter.
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, call, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.wa import WashingtonAdapter


def test_wa_adapter_registered():
    import results.adapters.wa  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "WA" in list_supported_states()
    assert get_adapter("WA") is WashingtonAdapter
    assert get_adapter("wa") is WashingtonAdapter


def test_fetch_results_no_slug():
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "wa_votewa:test"
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "enr_slug" in result.notes


def test_fetch_results_version_unchanged_uses_as_of():
    """If asOf matches cache, returns unchanged=True without fetching /data."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 2

    meta_payload = {
        "asOf": "2026-05-13T13:05:15.0369431Z",
        "lastUpdated": "2026-05-11T14:08:47Z",
        "isOfficialResults": True,
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-05-13T13:05:15.0369431Z"

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=2)

    assert result.unchanged is True
    assert result.source_version == "2026-05-13T13:05:15.0369431Z"
    assert result.rows == []
    assert mock_get.call_count == 1


def test_fetch_results_falls_back_to_last_updated_for_version():
    """When asOf is absent, version comes from lastUpdated."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 3

    meta_payload = {
        "lastUpdated": "2026-05-11T14:08:47Z",
        "isOfficialResults": False,
    }
    data_payload = {"jurisdiction": {}, "localityElections": [], "ballotItems": []}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=3)

    assert result.source_version == "2026-05-11T14:08:47Z"
    assert result.unchanged is False


def test_fetch_results_state_level_ballot_measure():
    """State-level BallotMeasure rows have jurisdiction_fragment='' and votewa raw IDs."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 2

    meta_payload = {"asOf": "2026-05-13T13:05:15Z", "isOfficialResults": True}
    data_payload = {
        "localityElections": [],
        "ballotItems": [
            {
                "id": "01000000-b872-6dac-8b23-08de95a613ed",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Rochester Fire District"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "nativeId": "yes-001",
                            "voteCount": 5000,
                            "votePercent": 60.0,
                            "isWinner": None,
                        }
                    ]
                },
            }
        ],
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=2)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.option_label == "Yes"
    assert row.vote_count == 5000
    assert row.jurisdiction_fragment == ""
    assert row.raw["votewa_ballot_item_id"] == "01000000-b872-6dac-8b23-08de95a613ed"
    assert row.raw["votewa_native_id"] == "yes-001"
    assert row.result_type == "official"


def test_fetch_results_county_fanout():
    """localityElections triggers a county data fetch; county rows have jurisdiction_fragment set."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 4

    meta_payload = {"asOf": "2026-05-13T13:05:15Z", "isOfficialResults": False}
    data_payload = {
        "localityElections": [
            {
                "jurisdiction": {"shortName": "mason-county-wa", "id": "some-guid"},
            }
        ],
        "ballotItems": [],
    }
    county_payload = {
        "ballotItems": [
            {
                "id": "county-item-001",
                "parentId": "state-agg-001",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Mason County Fire Levy"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "nativeId": "yes-c",
                            "voteCount": 1200,
                            "votePercent": 55.0,
                        }
                    ]
                },
            }
        ]
    }

    meta_resp = MagicMock()
    meta_resp.json.return_value = meta_payload
    data_resp = MagicMock()
    data_resp.json.return_value = data_payload
    county_resp = MagicMock()
    county_resp.json.return_value = county_payload

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        mock_get.side_effect = [meta_resp, data_resp, county_resp]

        result = adapter.fetch_results(None, election_id=4)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.jurisdiction_fragment == "mason-county-wa"
    assert row.raw["votewa_ballot_item_id"] == "county-item-001"
    assert row.raw["votewa_parent_ballot_item_id"] == "state-agg-001"
    assert row.vote_count == 1200
    assert mock_get.call_count == 3


def test_fetch_results_county_error_does_not_abort():
    """A failed county fetch is logged and skipped; state rows still returned."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 5

    meta_payload = {"asOf": "v1", "isOfficialResults": True}
    data_payload = {
        "localityElections": [
            {"jurisdiction": {"shortName": "broken-county-wa"}}
        ],
        "ballotItems": [
            {
                "id": "state-item-001",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Statewide Prop"}],
                "summaryResults": {
                    "ballotOptions": [
                        {"name": [{"languageId": "en", "text": "Yes"}], "nativeId": "s-yes",
                         "voteCount": 900, "votePercent": 50.0}
                    ]
                },
            }
        ],
    }

    meta_resp = MagicMock()
    meta_resp.json.return_value = meta_payload
    data_resp = MagicMock()
    data_resp.json.return_value = data_payload

    import requests as req_lib
    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        mock_get.side_effect = [meta_resp, data_resp, req_lib.ConnectionError("refused")]

        result = adapter.fetch_results(None, election_id=5)

    assert len(result.rows) == 1
    assert result.rows[0].jurisdiction_fragment == ""


def test_voter_portal_endpoints_never_called():
    """The adapter must not call voter.votewa.gov endpoints."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 6

    meta_payload = {"asOf": "v1", "isOfficialResults": True}
    data_payload = {"localityElections": [], "ballotItems": []}

    called_urls: list[str] = []

    def capture_get(url, **kwargs):
        called_urls.append(url)
        resp = MagicMock()
        resp.json.return_value = meta_payload if "data" not in url else data_payload
        return resp

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get", side_effect=capture_get), \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        adapter.fetch_results(None, election_id=6)

    for url in called_urls:
        assert "voter.votewa.gov" not in url, f"Voter portal URL was called: {url}"
