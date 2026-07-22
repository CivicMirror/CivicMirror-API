"""
Unit tests for PaSosClient's WAF-challenge retry logic and the duplicate
#dataJson locator fix (both confirmed live 2026-07-22 — see client.py
module docstring). Playwright is mocked; no browser or network calls.
"""
from unittest.mock import MagicMock

import pytest

from integrations.pa_sos.client import PaSosClient
from integrations.pa_sos.exceptions import PaSosRetryableError


def _make_client():
    client = PaSosClient.__new__(PaSosClient)
    client.base_url = "https://www.pavoterservices.beta.pa.gov"
    client.timeout_ms = 60000
    client._page = MagicMock()
    return client


class TestGotoChallengeRetry:
    def test_clears_on_first_attempt(self):
        client = _make_client()
        client._page.content.return_value = "<html>real page</html>"

        client._goto("https://example.test/page.aspx")

        assert client._page.goto.call_count == 1

    def test_retries_through_pardon_our_interruption_interstitial(self):
        client = _make_client()
        client._page.content.side_effect = [
            "<html><title>Pardon Our Interruption</title></html>",
            "<html>real page</html>",
        ]

        client._goto("https://example.test/page.aspx")

        assert client._page.goto.call_count == 2

    def test_retries_through_incapsula_iframe_challenge(self):
        client = _make_client()
        client._page.content.side_effect = [
            '<iframe>Request unsuccessful. Incapsula incident ID: 123</iframe>',
            "<html>real page</html>",
        ]

        client._goto("https://example.test/page.aspx")

        assert client._page.goto.call_count == 2

    def test_treats_mid_challenge_nav_abort_as_retryable_not_fatal(self):
        """The challenge script can issue a client-side redirect mid-load,
        aborting Playwright's own navigation (net::ERR_ABORTED). That's
        part of the challenge, not a real failure."""
        client = _make_client()
        client._page.goto.side_effect = [
            Exception("net::ERR_ABORTED"),
            None,
        ]
        client._page.content.return_value = "<html>real page</html>"

        client._goto("https://example.test/page.aspx")

        assert client._page.goto.call_count == 2

    def test_raises_retryable_error_after_exhausting_attempts(self):
        client = _make_client()
        client._page.content.return_value = "<html><title>Pardon Our Interruption</title></html>"

        with pytest.raises(PaSosRetryableError):
            client._goto("https://example.test/page.aspx")

        assert client._page.goto.call_count == 3


class TestFetchCandidateListDataJsonLocator:
    def test_uses_first_dataJson_match(self):
        """ElectionInfo.aspx renders two #dataJson inputs (one populated,
        one empty); .first must be used to avoid a Playwright strict-mode
        violation and reliably get the populated one."""
        client = _make_client()
        client._page.content.return_value = "<html>real page</html>"
        client._page.locator.return_value.evaluate.return_value = "153"

        first_locator = MagicMock()
        first_locator.get_attribute.return_value = '[{"CandidateID": 1}]'
        client._page.locator.return_value.first = first_locator

        result = client.fetch_candidate_list(153)

        assert result == '[{"CandidateID": 1}]'
        first_locator.get_attribute.assert_called_once_with("value")

    def test_selects_dropdown_when_election_id_differs(self):
        client = _make_client()
        client._page.content.return_value = "<html>real page</html>"
        client._page.locator.return_value.evaluate.return_value = "100"

        first_locator = MagicMock()
        first_locator.get_attribute.return_value = '[{"CandidateID": 2}]'
        client._page.locator.return_value.first = first_locator

        client.fetch_candidate_list(153)

        client._page.select_option.assert_called_once_with(
            "#ctl00_ContentPlaceHolder1_ReportElectionDropDown", value="153"
        )

    def test_raises_when_dropdown_has_no_value(self):
        client = _make_client()
        client._page.content.return_value = "<html>real page</html>"
        client._page.locator.return_value.evaluate.return_value = None

        with pytest.raises(PaSosRetryableError):
            client.fetch_candidate_list(153)

    def test_raises_when_dataJson_empty(self):
        client = _make_client()
        client._page.content.return_value = "<html>real page</html>"
        client._page.locator.return_value.evaluate.return_value = "153"

        first_locator = MagicMock()
        first_locator.get_attribute.return_value = ""
        client._page.locator.return_value.first = first_locator

        with pytest.raises(PaSosRetryableError):
            client.fetch_candidate_list(153)

    def test_wraps_persistent_waf_challenge_as_retryable(self):
        client = _make_client()
        client._page.content.return_value = "<html><title>Pardon Our Interruption</title></html>"

        with pytest.raises(PaSosRetryableError):
            client.fetch_candidate_list(153)


class TestFetchCandidateDetail:
    def test_returns_page_content(self):
        client = _make_client()
        client._page.content.return_value = "<html>candidate detail</html>"

        result = client.fetch_candidate_detail(42)

        assert result == "<html>candidate detail</html>"

    def test_wraps_challenge_failure_as_retryable(self):
        client = _make_client()
        client._page.content.return_value = "<html><title>Pardon Our Interruption</title></html>"

        with pytest.raises(PaSosRetryableError):
            client.fetch_candidate_detail(42)
