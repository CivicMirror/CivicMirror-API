from unittest.mock import MagicMock

import pytest

from integrations.ga_sos.client import GaSosClient
from integrations.ga_sos.exceptions import GaSosError, GaSosRetryableError


def _response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.side_effect = None
    return resp


def test_list_elections_reads_jurisdiction_catalog():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({
        "elections": [{"publicElectionId": "06162026GeneralPrimaryRunoff"}]
    }))

    rows = client.list_elections()

    assert rows == [{"publicElectionId": "06162026GeneralPrimaryRunoff"}]
    assert client._session.get.call_args.args[0] == (
        "https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia"
    )


def test_get_election_data_uses_opaque_public_id():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({"ballotItems": []}))

    assert client.get_election_data("06162026GeneralPrimaryRunoff") == {"ballotItems": []}
    assert client._session.get.call_args.args[0].endswith(
        "/elections/Georgia/06162026GeneralPrimaryRunoff/data"
    )


def test_get_ballot_item_detail_builds_detail_endpoint():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({"ballotItemWithBreakdown": {}}))

    client.get_ballot_item_detail("06162026GeneralPrimaryRunoff", "ballot-item-uuid")

    assert client._session.get.call_args.args[0].endswith(
        "/elections/Georgia/06162026GeneralPrimaryRunoff/data/ballot-item/ballot-item-uuid"
    )


def test_get_media_export_uses_cdn_base():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({"results": {}}))

    client.get_media_export("Georgia/export-06162026GeneralPrimaryRunoff.json")

    assert client._session.get.call_args.args[0] == (
        "https://results.sos.ga.gov/cdn/results/Georgia/export-06162026GeneralPrimaryRunoff.json"
    )


def test_404_is_non_retryable():
    client = GaSosClient(max_retries=0)
    resp = _response({}, status_code=404)
    client._session.get = MagicMock(return_value=resp)

    with pytest.raises(GaSosError):
        client.get_election_metadata("missing")


def test_503_is_retryable():
    client = GaSosClient(max_retries=0)
    client._session.get = MagicMock(return_value=_response({}, status_code=503))

    with pytest.raises(GaSosRetryableError):
        client.get_jurisdiction()
