from __future__ import annotations

from unittest.mock import MagicMock, patch


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
