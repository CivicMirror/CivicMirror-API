"""
Unit tests for the ClarityAdapter (JSON API path).
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.clarity import ClarityAdapter, _is_winner, _safe_float, _safe_int

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def test_safe_int_normal():
    assert _safe_int(1234) == 1234


def test_safe_int_comma_string():
    assert _safe_int("1,234") == 1234


def test_safe_int_none():
    assert _safe_int(None) == 0


def test_safe_int_empty():
    assert _safe_int("") == 0


def test_safe_float_normal():
    assert _safe_float(52.3) == 52.3


def test_safe_float_percent_string():
    assert _safe_float("52.3%") == 52.3


def test_safe_float_none():
    assert _safe_float(None) is None


def test_is_winner_int_one():
    assert _is_winner(1) is True


def test_is_winner_int_zero():
    assert _is_winner(0) is False


def test_is_winner_string_zero():
    # Clarity may return string "0"; bool("0") would be True — must be False
    assert _is_winner("0") is False


def test_is_winner_string_one():
    assert _is_winner("1") is True


def test_is_winner_none():
    assert _is_winner(None) is None


# ---------------------------------------------------------------------------
# ClarityAdapter._parse_contests
# ---------------------------------------------------------------------------

class ConcreteClarity(ClarityAdapter):
    state = "XX"


def make_contest(**kwargs):
    base = {
        "C": "U.S. SENATE",
        "CH": ["Alice Smith", "Bob Jones"],
        "V": [80000, 20000],
        "PCT": [80.0, 20.0],
        "W": [1, 0],
        "PR": 50,
        "TP": 55,
    }
    base.update(kwargs)
    return base


def test_parse_contests_basic():
    adapter = ConcreteClarity()
    contests = [make_contest()]
    rows = adapter._parse_contests(contests, "999")

    assert len(rows) == 2
    assert rows[0].office_title == "U.S. SENATE"
    assert rows[0].candidate_name == "Alice Smith"
    assert rows[0].vote_count == 80000
    assert rows[0].vote_pct == 80.0
    assert rows[0].is_winner is True
    assert rows[0].result_type == "unofficial"
    assert rows[0].option_label is None

    assert rows[1].candidate_name == "Bob Jones"
    assert rows[1].is_winner is False


def test_parse_contests_empty():
    adapter = ConcreteClarity()
    rows = adapter._parse_contests([], "999")
    assert rows == []


def test_parse_contests_missing_votes():
    adapter = ConcreteClarity()
    contest = {"C": "Governor", "CH": ["Only Candidate"], "V": [], "PCT": [], "W": []}
    rows = adapter._parse_contests([contest], "999")
    assert len(rows) == 1
    assert rows[0].vote_count == 0
    assert rows[0].vote_pct is None
    assert rows[0].is_winner is None


def test_parse_contests_skips_none_names():
    adapter = ConcreteClarity()
    contest = make_contest(CH=[None, "Bob"], V=[0, 100], PCT=[0.0, 100.0], W=[0, 1])
    rows = adapter._parse_contests([contest], "999")
    assert len(rows) == 1
    assert rows[0].candidate_name == "Bob"


def test_parse_contests_non_dict_entry_skipped():
    adapter = ConcreteClarity()
    rows = adapter._parse_contests(["not_a_dict", make_contest()], "999")
    assert len(rows) == 2  # only the valid contest produced rows


def test_parse_contests_multiple_contests():
    adapter = ConcreteClarity()
    contests = [
        make_contest(**{"C": "U.S. SENATE", "CH": ["A", "B"], "V": [1, 2], "PCT": [33, 67], "W": [0, 1]}),
        make_contest(**{"C": "GOVERNOR", "CH": ["C"], "V": [500], "PCT": [100.0], "W": [1]}),
    ]
    rows = adapter._parse_contests(contests, "999")
    assert len(rows) == 3
    senate_rows = [r for r in rows if r.office_title == "U.S. SENATE"]
    assert len(senate_rows) == 2


def test_parse_contests_raw_contains_version():
    adapter = ConcreteClarity()
    rows = adapter._parse_contests([make_contest()], "371599")
    assert rows[0].raw["ver"] == "371599"


# ---------------------------------------------------------------------------
# ClarityAdapter.fetch_results — integration with mocked HTTP + DB
# ---------------------------------------------------------------------------

SUMMARY_JSON = [
    {
        "C": "U.S. SENATE",
        "CH": ["ALICE SMITH", "BOB JONES"],
        "V": [80032, 22736],
        "PCT": [66.49, 18.89],
        "W": [0, 0],
        "PR": 51,
        "TP": 55,
    }
]


def _make_election(results_url="https://results.enr.clarityelections.com/WV/126209/"):
    election = MagicMock()
    election.pk = 1
    election.results_url = results_url
    election.election_date = "2026-05-13"
    return election


@pytest.fixture
def mock_requests():
    with patch("results.adapters.clarity.requests") as m:
        yield m


@pytest.fixture
def mock_election():
    with patch("results.adapters.clarity.Election") as MockElection:
        e = _make_election()
        MockElection.objects.get.return_value = e
        yield e


@pytest.fixture
def mock_cache():
    with patch("results.adapters.clarity.cache") as m:
        m.get.return_value = None  # cache miss by default
        yield m


@pytest.mark.django_db
def test_fetch_results_no_results_url(mock_requests, mock_cache):
    with patch("results.adapters.clarity.Election") as MockElection:
        e = _make_election(results_url="")
        MockElection.objects.get.return_value = e
        adapter = ConcreteClarity()
        result = adapter.fetch_results("2026-05-13", 1)

    assert result.mapping_confidence == "none"
    assert "no results_url" in result.notes
    mock_requests.get.assert_not_called()


@pytest.mark.django_db
def test_fetch_results_version_unchanged(mock_requests, mock_election, mock_cache):
    mock_cache.get.return_value = "371599"  # cached version = current

    ver_response = MagicMock()
    ver_response.text = "371599"
    mock_requests.get.return_value = ver_response

    adapter = ConcreteClarity()
    result = adapter.fetch_results("2026-05-13", 1)

    assert result.unchanged is True
    assert result.source_version == "371599"
    assert result.rows == []
    # summary.json should NOT have been fetched
    assert mock_requests.get.call_count == 1


@pytest.mark.django_db
def test_fetch_results_new_version_parses_rows(mock_requests, mock_election, mock_cache):
    mock_cache.get.return_value = "370000"  # outdated cached version

    ver_response = MagicMock()
    ver_response.text = "371599"

    summary_response = MagicMock()
    summary_response.json.return_value = SUMMARY_JSON

    mock_requests.get.side_effect = [ver_response, summary_response]

    adapter = ConcreteClarity()
    result = adapter.fetch_results("2026-05-13", 1)

    assert result.unchanged is False
    assert result.source_version == "371599"
    assert len(result.rows) == 2
    assert result.rows[0].candidate_name == "ALICE SMITH"
    assert result.rows[0].office_title == "U.S. SENATE"
    assert result.mapping_confidence == "full"
    # version cache should NOT be written by adapter
    mock_cache.set.assert_not_called()


@pytest.mark.django_db
def test_fetch_results_summary_as_dict_with_contests_key(mock_requests, mock_election, mock_cache):
    ver_response = MagicMock()
    ver_response.text = "371599"

    summary_response = MagicMock()
    summary_response.json.return_value = {"Contests": SUMMARY_JSON}

    mock_requests.get.side_effect = [ver_response, summary_response]

    adapter = ConcreteClarity()
    result = adapter.fetch_results("2026-05-13", 1)

    assert len(result.rows) == 2


@pytest.mark.django_db
def test_fetch_results_http_error_propagates(mock_requests, mock_election, mock_cache):
    import requests as req_lib

    mock_requests.get.side_effect = req_lib.RequestException("timeout")
    mock_requests.RequestException = req_lib.RequestException

    adapter = ConcreteClarity()
    with pytest.raises(req_lib.RequestException):
        adapter.fetch_results("2026-05-13", 1)


@pytest.mark.django_db
def test_fetch_results_sends_browser_user_agent(mock_requests, mock_election, mock_cache):
    """Both HTTP calls must include the browser User-Agent to bypass CloudFront blocking."""
    ver_response = MagicMock()
    ver_response.text = "371599"
    summary_response = MagicMock()
    summary_response.json.return_value = SUMMARY_JSON
    mock_requests.get.side_effect = [ver_response, summary_response]

    ConcreteClarity().fetch_results("2026-05-13", 1)

    for call in mock_requests.get.call_args_list:
        headers = call[1].get("headers", {})
        assert "User-Agent" in headers
        assert "Mozilla" in headers["User-Agent"]


@pytest.mark.django_db
def test_version_cache_key():
    assert ConcreteClarity.version_cache_key(42) == "clarity:ver:42"


# ---------------------------------------------------------------------------
# State adapter registration
# ---------------------------------------------------------------------------

def test_sc_adapter_registered():
    from results.adapters import co, sc, wv  # noqa: F401 — ensure @register runs
    from results.adapters.registry import get_adapter, list_supported_states
    assert "SC" in list_supported_states()
    adapter = get_adapter("SC")
    assert adapter is not None
    assert adapter.state == "SC"


def test_ia_adapter_registered():
    from results.adapters import co, ia, sc, wv  # noqa: F401 — ensure @register runs
    from results.adapters.registry import get_adapter, list_supported_states
    assert "IA" in list_supported_states()
    adapter = get_adapter("IA")
    assert adapter is not None
    assert adapter.state == "IA"

