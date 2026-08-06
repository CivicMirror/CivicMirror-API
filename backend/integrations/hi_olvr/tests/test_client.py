from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_parse_candidate_report_link_extracts_elid():
    from integrations.hi_olvr.parsers import parse_candidate_report_link

    html = '<p><a href="https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94">Candidate Report</a></p>'
    report_url, elid = parse_candidate_report_link(html)

    assert report_url == "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94"
    assert elid == "94"


@patch("integrations.hi_olvr.client.requests.Session")
def test_fetch_candidate_report_csv_posts_export_button(mock_session_cls):
    from integrations.hi_olvr.client import HawaiiOlvrClient

    session = mock_session_cls.return_value
    page = MagicMock()
    page.raise_for_status.return_value = None
    page.text = (
        '<form method="post">'
        '<input type="hidden" name="__VIEWSTATE" value="state" />'
        '<input type="hidden" name="ctl00$cphFooter$ddlElection" value="94" />'
        '<input type="submit" name="ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl00$ExportToPdfButton" value="" class="rgExpPDF" />'
        '<input type="submit" name="ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl00$ExportToCsvButton" value="" class="rgExpCSV" />'
        '</form>'
    )
    csv = MagicMock()
    csv.raise_for_status.return_value = None
    csv.headers = {"content-type": "text/csv; charset=utf-8"}
    csv.content = b'"Contests","Party"\n'

    session.get.return_value = page
    session.post.return_value = csv

    client = HawaiiOlvrClient(timeout=1)
    content = client.fetch_candidate_report_csv("https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94")

    assert content == b'"Contests","Party"\n'
    assert session.post.call_args.kwargs["data"]["__VIEWSTATE"] == "state"
    assert session.post.call_args.kwargs["data"]["ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl00$ExportToCsvButton"] == ""


@patch("integrations.hi_olvr.client.requests.Session")
def test_fetch_candidate_report_csv_excludes_other_submit_buttons(mock_session_cls):
    # Other submit buttons (PDF export, pagination, clear filter) must not be
    # included in the postback - submitting them alongside the CSV button
    # makes ASP.NET resolve the click to the wrong control (e.g. "Next Page"),
    # so the response is the re-rendered grid page instead of a CSV export.
    from integrations.hi_olvr.client import HawaiiOlvrClient

    session = mock_session_cls.return_value
    page = MagicMock()
    page.raise_for_status.return_value = None
    page.text = (
        '<form method="post">'
        '<input type="hidden" name="__VIEWSTATE" value="state" />'
        '<input type="submit" name="ctl00$...$clrRdgFilter" value="Clear Filter" />'
        '<input type="submit" name="ctl00$...$ExportToPdfButton" value="" class="rgExpPDF" />'
        '<input type="submit" name="ctl00$...$ExportToCsvButton" value="" class="rgExpCSV" />'
        '<input type="submit" name="ctl00$...$ctl28" value=" " title="Next Page" class="rgPageNext" />'
        '</form>'
    )
    csv = MagicMock()
    csv.raise_for_status.return_value = None
    csv.headers = {"content-type": "text/csv; charset=utf-8"}
    csv.content = b'"Contests","Party"\n'

    session.get.return_value = page
    session.post.return_value = csv

    client = HawaiiOlvrClient(timeout=1)
    client.fetch_candidate_report_csv("https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94")

    posted = session.post.call_args.kwargs["data"]
    assert "ctl00$...$ExportToCsvButton" in posted
    assert "ctl00$...$ExportToPdfButton" not in posted
    assert "ctl00$...$clrRdgFilter" not in posted
    assert "ctl00$...$ctl28" not in posted


# The real page renders the cycle selector as <select>, not <input>. Omitting it
# lets the portal's session cookie decide which election year gets exported.
_SELECT_PAGE = (
    '<form method="post">'
    '<input type="hidden" name="__VIEWSTATE" value="state" />'
    '<select name="ctl00$cphFooter$ddlElection" id="cphFooter_ddlElection">'
    '<option selected="selected" value="94">2026 Candidate Report</option>'
    '<option value="92">2024 Candidate Report</option>'
    '</select>'
    '<input type="submit" name="ctl00$...$ExportToCsvButton" value="" class="rgExpCSV" />'
    '</form>'
)


def _csv_client(mock_session_cls, page_text):
    from integrations.hi_olvr.client import HawaiiOlvrClient

    session = mock_session_cls.return_value
    page = MagicMock()
    page.raise_for_status.return_value = None
    page.text = page_text
    csv = MagicMock()
    csv.raise_for_status.return_value = None
    csv.headers = {"content-type": "text/csv; charset=utf-8"}
    csv.content = b'"Contests","Party"\n'
    session.get.return_value = page
    session.post.return_value = csv
    return HawaiiOlvrClient(timeout=1), session


@patch("integrations.hi_olvr.client.requests.Session")
def test_fetch_candidate_report_csv_posts_election_select(mock_session_cls):
    client, session = _csv_client(mock_session_cls, _SELECT_PAGE)

    client.fetch_candidate_report_csv("https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94")

    assert session.post.call_args.kwargs["data"]["ctl00$cphFooter$ddlElection"] == "94"


@patch("integrations.hi_olvr.client.requests.Session")
def test_fetch_candidate_report_csv_accepts_matching_cycle(mock_session_cls):
    client, _ = _csv_client(mock_session_cls, _SELECT_PAGE)

    content = client.fetch_candidate_report_csv(
        "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94", expected_elid="94",
    )

    assert content == b'"Contests","Party"\n'


@patch("integrations.hi_olvr.client.requests.Session")
def test_fetch_candidate_report_csv_rejects_wrong_cycle(mock_session_cls):
    from integrations.hi_olvr.exceptions import HawaiiOlvrError

    client, _ = _csv_client(mock_session_cls, _SELECT_PAGE)

    # Session cookie pinned the portal to 2026 while we asked for 2024; the
    # export must fail loudly rather than return the wrong year's candidates.
    with pytest.raises(HawaiiOlvrError, match="served election 94, expected 92"):
        client.fetch_candidate_report_csv(
            "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=92", expected_elid="92",
        )
