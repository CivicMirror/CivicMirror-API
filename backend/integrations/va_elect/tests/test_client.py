"""
Unit tests for the VaElectClient.
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, patch

import pytest

from integrations.va_elect.client import (
    VaElectClient,
    _parse_candidate_list_html,
)

# ---------------------------------------------------------------------------
# get_election_uuid
# ---------------------------------------------------------------------------

def test_get_election_uuid_normal():
    data = {"jurisdiction": {"bannerUrl": "d2c804ee-4ec2-46bb-91d7-5b41526eab03/BannerImage_abc.png"}}
    assert VaElectClient.get_election_uuid(data) == "d2c804ee-4ec2-46bb-91d7-5b41526eab03"


def test_get_election_uuid_missing():
    assert VaElectClient.get_election_uuid({}) is None
    assert VaElectClient.get_election_uuid({"jurisdiction": {}}) is None


def test_get_election_uuid_no_slash():
    data = {"jurisdiction": {"bannerUrl": "some-uuid-no-slash"}}
    assert VaElectClient.get_election_uuid(data) is None


# ---------------------------------------------------------------------------
# get_report_urls
# ---------------------------------------------------------------------------

_SAMPLE_DATA = {
    "jurisdiction": {
        "bannerUrl": "d2c804ee-4ec2-46bb-91d7-5b41526eab03/BannerImage_0f5830da.png"
    },
    "publicReportCategories": [
        {
            "categoryName": None,
            "reports": [
                {"reportName": "Election Results", "blobName": "Election Results_9b503992.csv", "order": 0},
                {"reportName": "Election Winners", "blobName": "Election Winners_cb94cd14.csv", "order": 0},
            ],
        },
        {
            "categoryName": "Other Reports",
            "reports": [
                {"reportName": "EnrAbsenteeRawCSV", "blobName": "EnrAbsenteeRawCSV_94488b5c.csv", "order": 1},
            ],
        },
    ],
}


def test_get_report_urls_count():
    reports = VaElectClient.get_report_urls(_SAMPLE_DATA)
    assert len(reports) == 3


def test_get_report_urls_structure():
    reports = VaElectClient.get_report_urls(_SAMPLE_DATA)
    names = [r["report_name"] for r in reports]
    assert "Election Results" in names
    assert "EnrAbsenteeRawCSV" in names


def test_get_report_urls_cdn_pattern():
    reports = VaElectClient.get_report_urls(_SAMPLE_DATA)
    results_report = next(r for r in reports if r["report_name"] == "Election Results")
    assert results_report["url"].startswith(
        "https://enr.elections.virginia.gov/cdn/results/d2c804ee-4ec2-46bb-91d7-5b41526eab03/"
    )
    assert "Election%20Results" in results_report["url"]


def test_get_report_urls_no_uuid():
    reports = VaElectClient.get_report_urls({"jurisdiction": {}, "publicReportCategories": []})
    assert reports == []


# ---------------------------------------------------------------------------
# Slug discovery
# ---------------------------------------------------------------------------

_SLUG_PAGE_HTML = """
<html><body>
<a href="/results/public/Virginia/2025-November-General">2025 November General</a>
<a href="/results/public/Virginia/2025-June-Republican-Primary">2025 June Republican Primary</a>
<a href="/results/public/Virginia/2024NovemberGeneral">2024 November General</a>
<a href="/results/public/Virginia/2025-April-8-Town-of-Marion-Special_">Special</a>
<a href="/other/page">Other</a>
</body></html>
"""


def test_get_election_slugs():
    client = VaElectClient()
    mock_resp = MagicMock()
    mock_resp.text = _SLUG_PAGE_HTML

    with patch.object(client, "_get", return_value=mock_resp):
        slugs = client.get_election_slugs()

    assert "2025-November-General" in slugs
    assert "2025-June-Republican-Primary" in slugs
    assert "2024NovemberGeneral" in slugs
    # Trailing underscore edge case preserved exactly
    assert "2025-April-8-Town-of-Marion-Special_" in slugs
    # Non-ENR links filtered out
    assert len(slugs) == 4


def test_get_election_slugs_deduplicates():
    html = """
    <html><body>
    <a href="/results/public/Virginia/2025-November-General">Link 1</a>
    <a href="/results/public/Virginia/2025-November-General">Link 2 (dupe)</a>
    </body></html>
    """
    client = VaElectClient()
    mock_resp = MagicMock()
    mock_resp.text = html

    with patch.object(client, "_get", return_value=mock_resp):
        slugs = client.get_election_slugs()

    assert slugs.count("2025-November-General") == 1


# ---------------------------------------------------------------------------
# Candidate list HTML parser
# ---------------------------------------------------------------------------

_CANDIDATE_TABLE_HTML = """
<html><body>
<table>
  <thead><tr>
    <th>Name on Ballot</th><th>Party</th><th>Office</th>
    <th>District</th><th>Incumbent</th><th>Campaign Email</th>
  </tr></thead>
  <tbody>
    <tr>
      <td>Jane Smith</td>
      <td>Democratic</td>
      <td>Governor</td>
      <td>Statewide</td>
      <td>No</td>
      <td><a href="mailto:jane@example.com">jane@example.com</a></td>
    </tr>
    <tr>
      <td>John Doe</td>
      <td>Republican</td>
      <td>Governor</td>
      <td>Statewide</td>
      <td>Yes</td>
      <td><a href="mailto:john@example.com">john@example.com</a></td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_parse_candidate_list_html_count():
    candidates = _parse_candidate_list_html(_CANDIDATE_TABLE_HTML)
    assert len(candidates) == 2


def test_parse_candidate_list_html_fields():
    candidates = _parse_candidate_list_html(_CANDIDATE_TABLE_HTML)
    jane = candidates[0]
    # _normalize_candidate_row maps "name_on_ballot" → "name" via _FIELD_ALIASES
    assert jane["name"] == "Jane Smith"
    assert jane["party"] == "Democratic"
    assert jane["incumbent"] is False

    john = candidates[1]
    assert john["incumbent"] is True


def test_parse_candidate_list_html_empty():
    candidates = _parse_candidate_list_html("<html><body><p>No table here</p></body></html>")
    assert candidates == []
