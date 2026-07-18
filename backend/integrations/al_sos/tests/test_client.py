from unittest.mock import MagicMock

import pytest

from integrations.al_sos.client import AlSosClient, extract_webforms_fields
from integrations.al_sos.exceptions import AlSosError


def test_extract_webforms_fields_reads_required_fields():
    html = """
    <input type="hidden" id="__VIEWSTATE" value="view-state" />
    <input type="hidden" id="__VIEWSTATEGENERATOR" value="generator" />
    <input type="hidden" id="__EVENTVALIDATION" value="validation" />
    """

    assert extract_webforms_fields(html) == {
        "__VIEWSTATE": "view-state",
        "__VIEWSTATEGENERATOR": "generator",
        "__EVENTVALIDATION": "validation",
    }


def test_extract_webforms_fields_raises_when_missing():
    with pytest.raises(AlSosError, match="missing __EVENTVALIDATION"):
        extract_webforms_fields('<input id="__VIEWSTATE" value="x" />')


def test_fetch_enr_export_posts_hidden_fields():
    session = MagicMock()
    get_response = MagicMock()
    get_response.text = """
    <input type="hidden" id="__VIEWSTATE" value="view-state" />
    <input type="hidden" id="__VIEWSTATEGENERATOR" value="generator" />
    <input type="hidden" id="__EVENTVALIDATION" value="validation" />
    """
    get_response.raise_for_status.return_value = None
    post_response = MagicMock()
    post_response.content = b"xlsx-bytes"
    post_response.headers = {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": "attachment; filename=sosEnrExport.xlsx",
    }
    post_response.raise_for_status.return_value = None
    session.get.return_value = get_response
    session.post.return_value = post_response

    content = AlSosClient(session=session).fetch_enr_export("1001295")

    assert content == b"xlsx-bytes"
    session.get.assert_called_once_with(
        "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx?ecode=1001295",
        timeout=30,
    )
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["data"]["__EVENTTARGET"] == "hlnkExportData"
    assert session.post.call_args.kwargs["data"]["__EVENTARGUMENT"] == ""
    assert session.post.call_args.kwargs["data"]["__VIEWSTATE"] == "view-state"
