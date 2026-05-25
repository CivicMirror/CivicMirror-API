"""
Tests for integrations.ma_sos.client — HTTP client methods.
All HTTP calls are mocked. No DB or real network required.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.ma_sos.client import MaSosClient
from integrations.ma_sos.exceptions import MaSosError, MaSosRetryableError


def _mock_response(text="", content=b"", status_code=200):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# get_election_ids
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.client.requests.Session")
def test_get_election_ids_calls_parsers(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session

    html = '<tr id="election-id-165300"><td>2024</td><td>President</td><td>Statewide</td><td>General</td></tr>'
    session.get.return_value = _mock_response(text=html)

    client = MaSosClient()
    rows = client.get_election_ids(2024, "General")

    assert len(rows) == 1
    assert rows[0]["election_id"] == 165300
    assert rows[0]["year"] == 2024
    assert rows[0]["stage"] == "General"


@patch("integrations.ma_sos.client.requests.Session")
def test_get_election_ids_retryable_error_returns_empty(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(status_code=503)

    client = MaSosClient(max_retries=0)
    rows = client.get_election_ids(2024, "General")
    assert rows == []


# ---------------------------------------------------------------------------
# download_election_csv
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.client.requests.Session")
def test_download_election_csv_returns_bytes(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(content=b"csv,data")

    client = MaSosClient()
    result = client.download_election_csv(165300)
    assert result == b"csv,data"


@patch("integrations.ma_sos.client.requests.Session")
def test_download_election_csv_correct_url(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(content=b"data")

    client = MaSosClient()
    client.download_election_csv(165300, precincts=False)

    call_url = session.get.call_args[0][0]
    assert "precincts_include:0" in call_url
    assert "165300" in call_url


@patch("integrations.ma_sos.client.requests.Session")
def test_download_election_csv_retryable_raises(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(status_code=503)

    client = MaSosClient(max_retries=0)
    with pytest.raises(MaSosRetryableError):
        client.download_election_csv(165300)


# ---------------------------------------------------------------------------
# get_ballot_question_metadata
# ---------------------------------------------------------------------------

BQ_HTML = """
<script>
election_data[11620] = {Election: {
  "id": "11620", "question_number": "1", "question": "Do you approve?",
  "question_alias": "Audit Legislature", "summary": "...",
  "is_amendment": "", "is_initiative_petition": "1", "is_referendum": "",
  "is_non_binding": "", "is_local": "", "is_county": "",
  "date": "2024-11-05", "year": "2024",
  "n_yes_votes": "2326911", "n_no_votes": "924289", "n_blank_votes": "261730",
  "pct_yes_votes": "0.715", "status": "published"
}};
</script>
"""


@patch("integrations.ma_sos.client.requests.Session")
def test_get_ballot_question_metadata_parses(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(text=BQ_HTML)

    client = MaSosClient()
    meta = client.get_ballot_question_metadata(11620)

    assert meta["bq_id"] == 11620
    assert meta["question_number"] == "1"


@patch("integrations.ma_sos.client.requests.Session")
def test_get_ballot_question_metadata_empty_raises(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(text="<html>no js</html>")

    client = MaSosClient()
    with pytest.raises(MaSosError):
        client.get_ballot_question_metadata(11620)


# ---------------------------------------------------------------------------
# get_ocpf_schedule
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.client.requests.Session")
def test_get_ocpf_schedule_returns_dict(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    resp = _mock_response()
    resp.json.return_value = {"year": 2024, "generalElectionDate": "11/5/2024"}
    session.get.return_value = resp

    client = MaSosClient()
    schedule = client.get_ocpf_schedule(2024)
    assert schedule["generalElectionDate"] == "11/5/2024"


@patch("integrations.ma_sos.client.requests.Session")
def test_get_ocpf_schedule_failure_returns_empty(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(status_code=503)

    client = MaSosClient(max_retries=0)
    schedule = client.get_ocpf_schedule(2024)
    assert schedule == {}


# ---------------------------------------------------------------------------
# 403 / 400 error handling
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.client.requests.Session")
def test_get_403_raises_mas_error(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.return_value = _mock_response(status_code=403)

    client = MaSosClient()
    with pytest.raises(MaSosError, match="403"):
        client.download_election_csv(165300)
