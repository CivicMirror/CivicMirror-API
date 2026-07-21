from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError


def test_county_codes_span_01_through_24():
    assert MdSbeClient.COUNTY_CODES[0] == "01"
    assert MdSbeClient.COUNTY_CODES[-1] == "24"
    assert len(MdSbeClient.COUNTY_CODES) == 24


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_builds_expected_url_and_decodes_utf8_sig(mock_get):
    response = MagicMock(status_code=200)
    # utf-8-sig decoding must strip a BOM if present, and be a no-op if absent.
    response.content = "﻿Office Name,Total Votes\r\nU.S. Senator,100\r\n".encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")

    assert text == "Office Name,Total Votes\r\nU.S. Senator,100\r\n"
    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://elections.maryland.gov/elections/archive/2024/election_data/"
        "PG24_01CountyResults.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_treats_soft_404_as_retryable(mock_get):
    """MD SBE returns HTTP 200 with a ~14KB 'Page Not Found' HTML body for missing
    pages instead of a real 404 — must be detected by content, not status code."""
    response = MagicMock(status_code=200)
    response.content = ("<html><body>Page Not Found</body></html>" + "x" * 14400).encode("utf-8")
    mock_get.return_value = response

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="99")


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_raises_on_connection_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")
