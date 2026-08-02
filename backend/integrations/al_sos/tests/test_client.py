from unittest.mock import MagicMock, patch

import pytest

from integrations.al_sos.client import AlSosClient, _AlabamaChainFixAdapter, extract_webforms_fields
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
    session.post.assert_called_once_with(
        "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx?ecode=1001295",
        data={
            "__EVENTTARGET": "hlnkExportData",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": "view-state",
            "__VIEWSTATEGENERATOR": "generator",
            "__EVENTVALIDATION": "validation",
        },
        timeout=60,
    )


def test_fetch_fcpa_race_search_builds_correct_url():
    client = AlSosClient()
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text='{"data":{"totalRecords":0,"list":[]},"success":true}')
        mock_get.return_value.raise_for_status = MagicMock()
        client.fetch_fcpa_race_search("160", 23, 1)

    url = mock_get.call_args[0][0]
    assert "page=com.acf.common.page.politicalracesearchresults" in url
    assert "election=160" in url
    assert "office=23" in url
    assert "pageNumber=1" in url
    assert "pageSize=100" in url


def test_fetch_fcpa_committee_detail_base64_encodes_id():
    client = AlSosClient()
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="<html></html>")
        mock_get.return_value.raise_for_status = MagicMock()
        client.fetch_fcpa_committee_detail(4834)

    url = mock_get.call_args[0][0]
    # base64("pcc") == "cGNj", base64("4834") == "NDgzNA==" -- verified against
    # the real captured URL in the FCPA HAR.
    assert "type=cGNj" in url
    assert "id=NDgzNA%3D%3D" in url or "id=NDgzNA==" in url


def test_chain_fix_adapter_mounted_for_hosts_missing_their_intermediate_cert():
    """
    Regression test for #132: sos.alabama.gov and fcpa.alabamavotes.gov omit
    their GlobalSign Atlas intermediate CA during the TLS handshake, so
    AlSosClient must route requests to those two hosts through the adapter
    that supplies the missing intermediate. www2.alabamavotes.gov (ENR
    export) sends a complete chain already and must NOT be routed through it,
    to avoid masking a real cert problem there in the future.
    """
    client = AlSosClient()

    sos_adapter = client.session.get_adapter("https://www.sos.alabama.gov/anything")
    fcpa_adapter = client.session.get_adapter("https://fcpa.alabamavotes.gov/anything")
    enr_adapter = client.session.get_adapter("https://www2.alabamavotes.gov/anything")

    assert isinstance(sos_adapter, _AlabamaChainFixAdapter)
    assert isinstance(fcpa_adapter, _AlabamaChainFixAdapter)
    assert not isinstance(enr_adapter, _AlabamaChainFixAdapter)
