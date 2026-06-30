"""
Unit tests for TxGoElectClient.
All HTTP calls are mocked — no network required.
"""
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from integrations.tx_goelect.client import TxGoElectClient
from integrations.tx_goelect.exceptions import TxGoElectError, TxGoElectRetryableError

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _b64(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


# ---------------------------------------------------------------------------
# get_election_constants
# ---------------------------------------------------------------------------

def test_get_election_constants_decodes_upload():
    """electionConstants response: {"upload": "<b64>"} → decoded dict."""
    payload = {"electionInfo": {"2026": {"P": {"53813": {"O": "Y"}}}}}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"upload": _b64(payload)}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_constants()

    assert result["electionInfo"]["2026"]["P"]["53813"]["O"] == "Y"


# ---------------------------------------------------------------------------
# get_election_data
# ---------------------------------------------------------------------------

def test_get_election_data_decodes_all_known_fields():
    """election/{id} response: each field individually b64-encoded → decoded dict."""
    home = {"ElecDate": "05022026", "CountiesReporting": {"CR": 5, "CT": 5}}
    lookups = {"Candidates": [{"ID": 1, "BN": "ALICE"}], "Office": [], "County": [], "OfficeType": []}
    empty = {}

    raw_response = {
        "Version": "enr/56181/21/",
        "Home": _b64(home),
        "Lookups": _b64(lookups),
        "Race": _b64(empty),
        "OfficeSummary": _b64(empty),
        "Federal": _b64(empty),
        "StateWide": _b64(empty),
        "StateWideQ": _b64(empty),
        "Districted": _b64(empty),
        "ReportList": _b64(empty),
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = raw_response
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert result["version"] == 21
    assert result["home"]["ElecDate"] == "05022026"
    assert result["lookups"]["Candidates"][0]["BN"] == "ALICE"


def test_get_election_data_tolerates_missing_fields():
    """Missing optional fields decode to {} without raising."""
    raw_response = {
        "Version": "enr/56181/1/",
        "Home": _b64({"ElecDate": "05022026", "CountiesReporting": {"CR": 0, "CT": 5}}),
        "Lookups": _b64({}),
        # All other fields absent
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = raw_response
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert result["office_summary"] == {}
    assert result["statewide_q"] == {}


def test_get_election_data_with_runoff_fixture():
    """Decode the 58315 runoff fixture — StateWide and Federal should be non-empty."""
    fixture = _load_fixture("enr_58315_election.json")
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(58315)

    assert isinstance(result["version"], int)
    # At least one of statewide or federal should be non-empty for a runoff
    assert result["statewide"] or result["federal"], (
        "Expected StateWide or Federal to be populated for election 58315"
    )


def test_get_election_data_with_real_fixture():
    """Decode the frozen SD4 fixture without raising."""
    fixture = _load_fixture("enr_56181_election.json")
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert isinstance(result["version"], int)
    assert result["home"]["ElecDate"] == "05022026"
    assert len(result["lookups"].get("Candidates", [])) > 0


# ---------------------------------------------------------------------------
# get_county_results
# ---------------------------------------------------------------------------

def test_get_county_results_with_real_fixture():
    """Decode the frozen SD4 countyInfo fixture without raising."""
    fixture = _load_fixture("enr_56181_county_info.json")
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_county_results(56181)

    assert isinstance(result, dict)
    # At least one county present
    assert len(result) > 0


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

def test_get_version_returns_integer():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": "enr/56181/21/"}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().get_version(56181) == 21


def test_get_version_returns_none_for_unknown_election():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": ""}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().get_version(99999) is None


# ---------------------------------------------------------------------------
# probe_election
# ---------------------------------------------------------------------------

def test_probe_election_true_when_live():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": "enr/59001/1/"}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().probe_election(59001) is True


def test_probe_election_false_when_not_live():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": ""}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().probe_election(59001) is False


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

def test_retries_on_503_then_succeeds():
    """Two 503s followed by a success → returns data, no exception raised."""
    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.json.return_value = {"Version": "enr/56181/21/"}

    fail_resp = MagicMock()
    fail_resp.status_code = 503

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.side_effect = [fail_resp, fail_resp, success_resp]
        client = TxGoElectClient()
        version = client.get_version(56181)

    assert version == 21


def test_raises_retryable_after_max_retries():
    """All attempts return 503 → TxGoElectRetryableError raised."""
    fail_resp = MagicMock()
    fail_resp.status_code = 503

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = fail_resp
        client = TxGoElectClient()
        with pytest.raises(TxGoElectRetryableError):
            client.get_version(56181)
