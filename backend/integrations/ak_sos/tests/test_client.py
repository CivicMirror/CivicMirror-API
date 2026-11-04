"""
Unit tests for AkSosClient. Playwright's page is mocked (same convention as
integrations.pa_sos.tests.test_client); no browser or network calls.
"""
from unittest.mock import MagicMock

import pytest

from integrations.ak_sos.client import AkSosClient
from integrations.ak_sos.exceptions import AkSosError, AkSosRetryableError


def _make_client():
    client = AkSosClient.__new__(AkSosClient)
    client.timeout_ms = 30000
    client._page = MagicMock()
    return client


def test_fetch_candidates_html_selects_election_then_contest_then_submits():
    client = _make_client()
    client._page.locator.return_value.first.inner_html.return_value = "<article>ok</article>"

    client.fetch_candidates_html("2026 Primary Election", "GOVERNOR / LIEUTENANT GOVERNOR")

    # Election must be selected (and its AJAX settle awaited) before Contest,
    # confirmed live: selecting Contest too early submits with stale hidden
    # fields and the server rejects it.
    select_calls = [c for c in client._page.locator.call_args_list]
    assert any(call.args[0] == "#field_stebs3" for call in select_calls)
    assert any(call.args[0] == "#field_cx3x52" for call in select_calls)
    client._page.locator.return_value.click.assert_called()


def test_fetch_candidates_html_returns_html_on_success():
    client = _make_client()
    client._page.locator.return_value.first.inner_html.return_value = "<article>real content</article>"

    html = client.fetch_candidates_html("2026 Primary Election", "GOVERNOR / LIEUTENANT GOVERNOR")

    assert html == "<article>real content</article>"


def test_fetch_candidates_html_raises_on_validation_error_banner():
    """
    Regression guard: every per-field "X cannot be blank." message is
    always present in the DOM as a hidden template (confirmed live, even on
    a fresh un-submitted page), so detection must key off the banner
    Formidable actually renders on a real failure, not those strings.
    """
    client = _make_client()
    client._page.locator.return_value.first.inner_html.return_value = (
        "<article>There was a problem with your submission. Errors are marked below.</article>"
    )

    with pytest.raises(AkSosError, match="validation failed"):
        client.fetch_candidates_html("2026 Primary Election", "GOVERNOR / LIEUTENANT GOVERNOR")


def test_goto_candidates_page_retries_then_raises():
    client = _make_client()
    client._page.goto.side_effect = Exception("net::ERR_TIMED_OUT")

    with pytest.raises(AkSosRetryableError):
        client._goto_candidates_page()

    assert client._page.goto.call_count == 3


def test_fetch_candidates_html_wraps_unexpected_errors_as_retryable():
    client = _make_client()
    client._page.goto.return_value = None
    client._page.wait_for_selector.return_value = None
    client._page.locator.side_effect = Exception("boom")

    with pytest.raises(AkSosRetryableError):
        client.fetch_candidates_html("2026 Primary Election", "GOVERNOR / LIEUTENANT GOVERNOR")
