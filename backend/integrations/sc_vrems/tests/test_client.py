"""
Tests for the SC VREMS client.
"""
from unittest.mock import MagicMock, patch

import pytest

from integrations.sc_vrems.client import VremsClient, _parse_candidate_table
from integrations.sc_vrems.exceptions import SCVremsRetryableError


@pytest.fixture
def client():
    c = VremsClient(timeout=5, max_retries=1)
    # Pre-inject a mock session so get_session() doesn't make real HTTP calls
    mock_session = MagicMock()
    c._session = mock_session
    return c, mock_session


def _mock_resp(status: int, json_data=None, text=""):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = json_data or {}
    mock.text = text
    mock.raise_for_status = MagicMock()
    return mock


# ------------------------------------------------------------------
# get_years
# ------------------------------------------------------------------

def test_get_years_parses_json(client):
    c, session = client
    session.get.return_value = _mock_resp(200, [{"electionYear": 2026}, {"electionYear": 2024}])
    result = c.get_years("General")
    assert result == [2026, 2024]


def test_get_years_retryable_on_503(client):
    c, session = client
    session.get.return_value = _mock_resp(503)
    with pytest.raises(SCVremsRetryableError):
        c.get_years("General")


# ------------------------------------------------------------------
# get_elections
# ------------------------------------------------------------------

def test_get_elections_injects_type(client):
    c, session = client
    payload = [{
        "electionId": "22598",
        "electionName": "Statewide Primary",
        "displayName": "6/9/2026 Statewide Primary",
        "electionDate": "2026-06-09T00:00:00",
        "filingPeriodBeginDate": "2026-03-16T12:00:00",
    }]
    session.get.return_value = _mock_resp(200, payload)
    result = c.get_elections("General", 2026)
    assert result[0]["electionType"] == "General"
    assert result[0]["electionId"] == "22598"


# ------------------------------------------------------------------
# get_all_elections deduplication
# ------------------------------------------------------------------

def test_get_all_elections_deduplicates(client):
    c, session = client

    duplicate_election = [{
        "electionId": "22598",
        "electionName": "Statewide Primary",
        "displayName": "6/9/2026 Statewide Primary",
        "electionDate": "2026-06-09T00:00:00",
        "filingPeriodBeginDate": "2026-03-16T12:00:00",
    }]

    # Same election returned for all three types
    session.get.return_value = MagicMock(
        status_code=200,
        raise_for_status=MagicMock(),
    )
    session.get.return_value.json.side_effect = [
        [{"electionYear": 2026}], duplicate_election,
        [{"electionYear": 2026}], duplicate_election,
        [{"electionYear": 2026}], duplicate_election,
    ]

    result = c.get_all_elections()
    assert len(result) == 1


# ------------------------------------------------------------------
# HTML table parser
# ------------------------------------------------------------------

_SAMPLE_HTML = """
<table id="gridCandidateSearch">
  <tbody>
    <tr data-key="12345">
      <td>Governor</td>
      <td></td>
      <td><a href="CandidateDetail/?candidateId=999&amp;electionId=22598&amp;searchType=Default">Jane Smith</a></td>
      <td></td>
      <td>Republican</td>
      <td>State</td>
      <td>Active</td>
    </tr>
    <tr data-key="12346">
      <td>Governor</td>
      <td></td>
      <td><a href="CandidateDetail/?candidateId=1000&amp;electionId=22598&amp;searchType=Default">John Doe</a></td>
      <td></td>
      <td>Democratic</td>
      <td>State</td>
      <td>Active</td>
    </tr>
  </tbody>
</table>
"""

_EMPTY_HTML = "<div>No results</div>"


def test_parse_candidate_table_two_candidates():
    result = _parse_candidate_table(_SAMPLE_HTML)
    assert len(result) == 2
    assert result[0]["name_on_ballot"] == "Jane Smith"
    assert result[0]["party"] == "Republican"
    assert result[0]["candidate_id"] == "12345"
    assert result[0]["candidate_detail_id"] == "999"
    assert result[0]["office"] == "Governor"
    assert result[0]["status"] == "Active"


def test_parse_candidate_table_empty_returns_empty():
    result = _parse_candidate_table(_EMPTY_HTML)
    assert result == []


def test_parse_candidate_table_extracts_filing_location():
    result = _parse_candidate_table(_SAMPLE_HTML)
    assert result[0]["filing_location"] == "State"
