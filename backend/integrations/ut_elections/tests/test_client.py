from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.ut_elections.client import UtElectionsClient
from integrations.ut_elections.exceptions import UtElectionsRetryableError

_URL = "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"


@patch("integrations.ut_elections.client.requests.Session.get")
def test_fetch_candidate_filing_workbook_returns_bytes(mock_get):
    response = MagicMock(status_code=200)
    response.content = b"PK\x03\x04fake-xlsx-bytes"
    mock_get.return_value = response

    client = UtElectionsClient()
    content = client.fetch_candidate_filing_workbook(_URL)

    assert content == b"PK\x03\x04fake-xlsx-bytes"
    assert mock_get.call_args[0][0] == _URL


@patch("integrations.ut_elections.client.requests.Session.get")
def test_fetch_candidate_filing_workbook_raises_on_non_200(mock_get):
    response = MagicMock(status_code=404)
    response.content = b"Not Found"
    mock_get.return_value = response

    client = UtElectionsClient()
    with pytest.raises(UtElectionsRetryableError):
        client.fetch_candidate_filing_workbook(_URL)


@patch("integrations.ut_elections.client.requests.Session.get")
def test_fetch_candidate_filing_workbook_raises_on_connection_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")

    client = UtElectionsClient()
    with pytest.raises(UtElectionsRetryableError):
        client.fetch_candidate_filing_workbook(_URL)
