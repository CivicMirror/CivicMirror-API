"""Tests for the Vermont SOS HTTP client."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.vt_sos.client import BASE_URL, VermontSosClient, normalize_category_path
from integrations.vt_sos.exceptions import VtSosError, VtSosRetryableError


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestNormalizeCategoryPath:
    def test_converts_backslashes_to_slashes(self):
        assert normalize_category_path("elections\\abc-f-123.json") == "elections/abc-f-123.json"

    def test_strips_leading_slash(self):
        assert normalize_category_path("/elections/abc.json") == "elections/abc.json"

    def test_handles_empty_string(self):
        assert normalize_category_path("") == ""


class TestListElections:
    def test_returns_parsed_list(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data=[{"electionGuid": "x"}])):
            result = client.list_elections()
        assert result == [{"electionGuid": "x"}]

    def test_hits_correct_url(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data=[])) as mock_get:
            client.list_elections()
        called_url = mock_get.call_args[0][0]
        assert called_url == f"{BASE_URL}/elections/elections.json"

    def test_raises_when_response_is_not_a_list(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data={"not": "a list"})):
            with pytest.raises(VtSosError):
                client.list_elections()


class TestGetElectionManifest:
    def test_returns_parsed_dict(self):
        client = VermontSosClient()
        manifest = {"electionDetails": {"electionGuid": "abc"}}
        with patch.object(client._session, "get", return_value=_mock_response(json_data=manifest)):
            result = client.get_election_manifest("abc")
        assert result == manifest

    def test_hits_guid_scoped_url(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data={})) as mock_get:
            client.get_election_manifest("a18f77e0-89f8-4a01-8d97-61a7c75ba200")
        called_url = mock_get.call_args[0][0]
        assert called_url == f"{BASE_URL}/elections/a18f77e0-89f8-4a01-8d97-61a7c75ba200.json"


class TestGetCategory:
    def test_normalizes_backslash_path_before_fetching(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data={"d": []})) as mock_get:
            client.get_category("elections\\abc-f-20260721220608.json")
        called_url = mock_get.call_args[0][0]
        assert called_url == f"{BASE_URL}/elections/abc-f-20260721220608.json"

    def test_parses_octet_stream_body_as_json(self):
        """Server serves JSON as application/octet-stream; client must not
        require a JSON Content-Type header to parse it."""
        client = VermontSosClient()
        resp = _mock_response(json_data={"d": [{"pid": 162}]})
        with patch.object(client._session, "get", return_value=resp):
            result = client.get_category("elections/abc.json")
        assert result == {"d": [{"pid": 162}]}

    def test_raises_when_response_is_not_a_dict(self):
        client = VermontSosClient()
        with patch.object(client._session, "get", return_value=_mock_response(json_data=[1, 2, 3])):
            with pytest.raises(VtSosError):
                client.get_category("elections/abc.json")


class TestRetryBehavior:
    def test_retries_on_503_then_succeeds(self):
        client = VermontSosClient(max_retries=2)
        responses = [_mock_response(status_code=503), _mock_response(json_data=[])]
        with patch.object(client._session, "get", side_effect=responses):
            result = client.list_elections()
        assert result == []

    def test_raises_retryable_after_exhausting_503_retries(self):
        client = VermontSosClient(max_retries=1)
        with patch.object(client._session, "get", return_value=_mock_response(status_code=503)):
            with pytest.raises(VtSosRetryableError):
                client.list_elections()

    def test_raises_retryable_on_network_error(self):
        client = VermontSosClient(max_retries=0)
        with patch.object(client._session, "get", side_effect=requests.ConnectionError("down")):
            with pytest.raises(VtSosRetryableError):
                client.list_elections()

    def test_404_on_category_is_retryable_not_fatal(self):
        """Category files can 404 transiently around a manifest's publication
        transition (new timestamped path not yet live) — treat as retryable."""
        client = VermontSosClient(max_retries=0)
        with patch.object(client._session, "get", return_value=_mock_response(status_code=404)):
            with pytest.raises(VtSosRetryableError):
                client.get_category("elections/abc.json")

    def test_raises_non_retryable_on_bad_json(self):
        client = VermontSosClient(max_retries=0)
        resp = _mock_response(status_code=200)
        resp.json.side_effect = ValueError("not json")
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(VtSosError):
                client.list_elections()
