from __future__ import annotations

import datetime
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from openpyxl import Workbook

from integrations.or_sos.client import (
    OrSosClient,
    find_result_links,
    parse_history_response,
    parse_public_view_guid,
    resolve_records_attachment_url,
)
from integrations.or_sos.exceptions import OrSosUnsupportedDocumentError
from integrations.or_sos.parsers import document_checksum, parse_result_document
from results.adapters.oregon import OregonAdapter

_HISTORY_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetListItemsResponse xmlns="http://schemas.microsoft.com/sharepoint/soap/">
      <GetListItemsResult>
        <listitems xmlns:s="uuid:BDC6E3F0-6DA3-11d1-A2A3-00AA00C14882"
          xmlns:rs="urn:schemas-microsoft-com:rowset" xmlns:z="#RowsetSchema">
          <rs:data ItemCount="1">
            <z:row
              ows_Election_x0020_Date="2026-05-19 00:00:00"
              ows_Election_x0020_Type="Primary Election"
              ows_Results="&lt;a href=&quot;https://records.sos.state.or.us/results.csv&quot;&gt;Official Results&lt;/a&gt;"
              ows_Modified="2026-06-30 12:00:00" />
          </rs:data>
        </listitems>
      </GetListItemsResult>
    </GetListItemsResponse>
  </soap:Body>
</soap:Envelope>"""


_VIEWS_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetViewCollectionResponse xmlns="http://schemas.microsoft.com/sharepoint/soap/">
      <GetViewCollectionResult>
        <Views>
          <View Name="{PUBLIC-GUID}" DisplayName="public" />
        </Views>
      </GetViewCollectionResult>
    </GetViewCollectionResponse>
  </soap:Body>
</soap:Envelope>"""


_CSV = b"Contest Name,Candidate Name,Total Votes,Vote Percent,Party\nGovernor,Alice Smith,1,55.5,DEM\nGovernor,Bob Jones,2,44.5,REP\n"


def _make_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Official Results"
    sheet.append(["Contest Name", "Candidate Name", "Total Votes", "Vote Percent", "Party"])
    sheet.append(["Governor", "Alice Smith", 100, 60.5, "DEM"])
    sheet.append(["Governor", "Bob Jones", 65, 39.5, "REP"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _make_election(source_metadata: dict | None = None):
    election = MagicMock()
    election.pk = 42
    election.election_date = datetime.date(2026, 5, 19)
    election.election_type = "primary"
    election.source_metadata = source_metadata or {}
    return election


def test_parse_public_view_guid():
    assert parse_public_view_guid(_VIEWS_XML) == "{PUBLIC-GUID}"


def test_parse_history_response_extracts_row():
    rows = parse_history_response(_HISTORY_XML)

    assert len(rows) == 1
    assert rows[0].election_date == datetime.date(2026, 5, 19)
    assert rows[0].election_type == "Primary Election"
    assert "results.csv" in rows[0].results_html
    assert rows[0].source_version == "2026-06-30 12:00:00"


def test_find_result_links_absolutizes_relative_urls():
    links = find_result_links('<a href="/elections/results.csv">Results</a>')

    assert links == ["https://sos.oregon.gov/elections/results.csv"]


def test_parse_result_document_csv():
    records = parse_result_document(_CSV, "https://example.test/results.csv")

    assert len(records) == 2
    assert records[0].office_title == "Governor"
    assert records[0].choice == "Alice Smith"
    assert records[0].vote_count == 1
    assert records[0].vote_pct == 55.5
    assert records[0].party == "DEM"


def test_parse_result_document_xlsx():
    records = parse_result_document(_make_xlsx(), "https://example.test/results.xlsx")

    assert len(records) == 2
    assert records[0].office_title == "Governor"
    assert records[0].choice == "Alice Smith"
    assert records[0].vote_count == 100
    assert records[0].vote_pct == 60.5
    assert records[0].source_file == "results.xlsx"


def test_parse_result_document_zip_with_xlsx():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("official/results.xlsx", _make_xlsx())

    records = parse_result_document(buffer.getvalue(), "https://example.test/results.zip")

    assert len(records) == 2
    assert records[0].source_file == "official/results.xlsx"


def test_parse_result_document_pdf_is_explicitly_unsupported():
    with pytest.raises(OrSosUnsupportedDocumentError):
        parse_result_document(b"%PDF", "https://example.test/results.pdf")


def test_resolve_records_attachment_url_prefers_downloadable_file():
    html = '<html><body><a href="/ORSOSWebDrawer/Recordpdf/123/results.xlsx">Download</a></body></html>'

    assert resolve_records_attachment_url(html, "https://records.sos.state.or.us/ORSOSWebDrawer/Recordhtml/123") == (
        "https://records.sos.state.or.us/ORSOSWebDrawer/Recordpdf/123/results.xlsx"
    )


def test_download_document_follows_records_viewer_attachment():
    html_response = MagicMock()
    html_response.headers = {"Content-Type": "text/html; charset=utf-8"}
    html_response.text = '<a href="/download/results.csv">CSV</a>'
    html_response.url = "https://records.sos.state.or.us/ORSOSWebDrawer/Recordhtml/123"
    html_response.content = b"<html></html>"

    file_response = MagicMock()
    file_response.headers = {"Content-Type": "text/csv"}
    file_response.url = "https://records.sos.state.or.us/download/results.csv"
    file_response.content = _CSV

    with patch("integrations.or_sos.client.requests.get", side_effect=[html_response, file_response]) as mock_get:
        content, resolved_url = OrSosClient().download_document(html_response.url)

    assert content == _CSV
    assert resolved_url == "https://records.sos.state.or.us/download/results.csv"
    assert mock_get.call_count == 2


def test_oregon_adapter_fetches_direct_csv_result():
    election = _make_election({"or_results_url": "https://records.sos.state.or.us/results.csv"})

    adapter = OregonAdapter()

    with patch("results.adapters.oregon.cache") as mock_cache, \
         patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.oregon.OrSosClient") as MockClient:
        mock_cache.get.return_value = None
        MockClient.return_value.download_document.return_value = (_CSV, "https://records.sos.state.or.us/results.csv")

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 2
    assert result.rows[0].office_title == "Governor"
    assert result.rows[0].candidate_name == "Alice Smith"
    assert result.rows[0].result_type == "official"


def test_oregon_adapter_returns_unchanged_when_checksum_matches():
    election = _make_election({"or_results_url": "https://records.sos.state.or.us/results.csv"})

    adapter = OregonAdapter()

    with patch("results.adapters.oregon.cache") as mock_cache, \
         patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.oregon.OrSosClient") as MockClient, \
         patch("results.adapters.oregon.parse_result_document") as mock_parse:
        MockClient.return_value.download_document.return_value = (_CSV, "https://records.sos.state.or.us/results.csv")
        expected_version = document_checksum(_CSV)
        mock_cache.get.return_value = expected_version

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.unchanged is True
    assert result.source_version == expected_version
    mock_parse.assert_not_called()


def test_oregon_adapter_unsupported_pdf_returns_partial():
    election = _make_election({"or_results_url": "https://records.sos.state.or.us/results.pdf"})

    adapter = OregonAdapter()

    with patch("results.adapters.oregon.cache") as mock_cache, \
         patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.oregon.OrSosClient") as MockClient:
        mock_cache.get.return_value = None
        MockClient.return_value.download_document.return_value = (b"%PDF", "https://records.sos.state.or.us/results.pdf")

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "partial"
    assert "not parsed yet" in result.notes


def test_oregon_adapter_returns_no_data_when_history_index_unavailable():
    election = _make_election()

    adapter = OregonAdapter()

    with patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.oregon.OrSosClient") as MockClient:
        MockClient.return_value.get_history_rows.side_effect = RuntimeError("401 Unauthorized")

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"
    assert "history index unavailable" in result.notes


def test_oregon_adapter_is_registered():
    # Importing the module runs @register even outside Django app startup.
    from results.adapters import oregon  # noqa: F401
    from results.adapters.registry import get_adapter

    assert get_adapter("OR") is OregonAdapter
