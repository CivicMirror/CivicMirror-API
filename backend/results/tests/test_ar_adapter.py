"""
Unit tests for the Arkansas TotalVote/TotalResults results adapter.
HTTP calls are mocked; tests marked django_db require a test database.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from results.adapters.ar import (
    ArkansasAdapter,
    _build_name_map,
    _parse_download,
    _safe_float,
    _safe_int,
)

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

def test_safe_int_normal():
    assert _safe_int(759241) == 759241


def test_safe_int_string():
    assert _safe_int("759241") == 759241


def test_safe_int_comma_string():
    assert _safe_int("1,190,172") == 1190172


def test_safe_int_none():
    assert _safe_int(None) == 0


def test_safe_int_invalid():
    assert _safe_int("abc") == 0


def test_safe_float_normal():
    assert _safe_float(64.2) == 64.2


def test_safe_float_percent_string():
    assert _safe_float("64.2%") == 64.2


def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_invalid():
    assert _safe_float("bad") is None


# ---------------------------------------------------------------------------
# _parse_download
# ---------------------------------------------------------------------------

_DOWNLOAD_PAYLOAD = {
    "electionDate": "2026-03-31",
    "timestamp": "2026-04-29T16:33:00Z",
    "races": [
        {
            "officeName": "REP Secretary of State",
            "numRunoff": 1,
            "resultsType": "certified",
            "reportingUnits": [
                {
                    "statePostal": "AR",
                    "stateName": "Arkansas",
                    "reportingUnitName": "Arkansas",
                    "level": "state",
                    "lastUpdated": "2026-04-29T16:33:00Z",
                    "precinctsReporting": 2863,
                    "precinctsTotal": 2863,
                    "precinctsReportingPct": 100,
                    "candidates": [
                        {
                            "first": "Bryan",
                            "last": "Norris",
                            "candidateID": "abc-001",
                            "ballotOrder": 0,
                            "voteCount": 40032,
                            "votePct": 49.44,
                            "winner": "",
                        },
                        {
                            "first": "Dennis",
                            "last": "Milligan",
                            "candidateID": "abc-002",
                            "ballotOrder": 1,
                            "voteCount": 40938,
                            "votePct": 50.56,
                            "winner": "X",
                        },
                    ],
                },
                {
                    # county-level unit — must be ignored
                    "statePostal": "AR",
                    "level": "county",
                    "reportingUnitName": "Pulaski",
                    "candidates": [
                        {"first": "Bryan", "last": "Norris", "candidateID": "abc-001",
                         "voteCount": 5000, "votePct": 40.0, "winner": ""},
                    ],
                },
            ],
        }
    ],
}


def test_parse_download_row_count():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    # 2 candidates × 1 state-level unit = 2 rows (county unit skipped)
    assert len(rows) == 2


def test_parse_download_office_title():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].office_title == "REP Secretary of State"


def test_parse_download_candidate_name():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].candidate_name == "Bryan Norris"
    assert rows[1].candidate_name == "Dennis Milligan"


def test_parse_download_vote_count():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].vote_count == 40032
    assert rows[1].vote_count == 40938


def test_parse_download_vote_pct():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].vote_pct == pytest.approx(49.44)
    assert rows[1].vote_pct == pytest.approx(50.56)


def test_parse_download_winner_x_is_true():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[1].is_winner is True


def test_parse_download_winner_empty_is_false():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].is_winner is False


def test_parse_download_certified_result_type_is_official():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].result_type == "official"
    assert rows[1].result_type == "official"


def test_parse_download_unofficial_result_type():
    payload = {
        "races": [
            {
                "officeName": "Governor",
                "resultsType": "unofficial",
                "reportingUnits": [
                    {
                        "level": "state",
                        "candidates": [
                            {"first": "Alice", "last": "Smith", "candidateID": "x",
                             "voteCount": 100, "votePct": 55.0, "winner": ""},
                        ],
                    }
                ],
            }
        ]
    }
    rows = _parse_download(payload)
    assert rows[0].result_type == "unofficial"


def test_parse_download_county_level_skipped():
    # The county-level unit in _DOWNLOAD_PAYLOAD should produce 0 rows
    # (covered by test_parse_download_row_count — this makes intent explicit)
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    for row in rows:
        # statewide votes for Norris = 40032; county votes = 5000 — must not appear
        assert row.vote_count != 5000


def test_parse_download_raw_contains_candidate_id():
    rows = _parse_download(_DOWNLOAD_PAYLOAD)
    assert rows[0].raw['candidateID'] == "abc-001"
    assert rows[0].raw['resultsType'] == "certified"


def test_parse_download_empty_races():
    assert _parse_download({"races": []}) == []


def test_parse_download_missing_races_key():
    assert _parse_download({}) == []


# ---------------------------------------------------------------------------
# _build_name_map
# ---------------------------------------------------------------------------

_SEARCH_PAYLOAD = {
    "response": {
        "contests": {
            "237": {
                "contestId": "237",
                "contestName": "U.S. Senate",
                "contestTypeCode": "FED",
                "choices": {
                    "501": {"id": "501", "name": "Alice Brown", "isWriteIn": False, "partyID": "1"},
                    "502": {"id": "502", "name": "Bob Green", "isWriteIn": False, "partyID": "2"},
                    "503": {"id": "503", "name": "Write-In", "isWriteIn": True, "partyID": "1"},
                },
            },
            "305": {
                "contestId": "305",
                "contestName": "Governor",
                "contestTypeCode": "STW",
                "choices": {
                    "601": {"id": "601", "name": "Carol White", "isWriteIn": False, "partyID": "2"},
                },
            },
        }
    }
}


def test_build_name_map_returns_all_contests():
    nm, _ = _build_name_map(_SEARCH_PAYLOAD)
    assert "237" in nm
    assert "305" in nm


def test_build_name_map_contest_name():
    nm, _ = _build_name_map(_SEARCH_PAYLOAD)
    assert nm["237"]["name"] == "U.S. Senate"
    assert nm["305"]["name"] == "Governor"


def test_build_name_map_choice_name():
    nm, _ = _build_name_map(_SEARCH_PAYLOAD)
    assert nm["237"]["choices"]["501"]["name"] == "Alice Brown"
    assert nm["237"]["choices"]["502"]["name"] == "Bob Green"


def test_build_name_map_write_in_flag():
    nm, _ = _build_name_map(_SEARCH_PAYLOAD)
    assert nm["237"]["choices"]["503"]["isWriteIn"] is True
    assert nm["237"]["choices"]["501"]["isWriteIn"] is False


def test_build_name_map_contest_types():
    _, ct = _build_name_map(_SEARCH_PAYLOAD)
    assert "FED" in ct
    assert "STW" in ct
    assert len(ct) == 2


def test_build_name_map_empty_response():
    nm, ct = _build_name_map({})
    assert nm == {}
    assert ct == set()


# ---------------------------------------------------------------------------
# ArkansasAdapter.fetch_results — mocked integration tests
# ---------------------------------------------------------------------------

def _make_election(source_metadata=None):
    e = MagicMock()
    e.pk = 42
    e.source_id = "ar_elect_test"
    e.source_metadata = source_metadata or {}
    return e


def _ver_response(last_updated="2026-04-29T16:33:00Z", is_official=True):
    m = MagicMock()
    m.json.return_value = {
        "versionID": "v1",
        "lastUpdated": last_updated,
        "isOfficial": is_official,
        "electionID": "b412bdef-test",
    }
    return m


def _download_response():
    m = MagicMock()
    m.json.return_value = _DOWNLOAD_PAYLOAD
    return m


_SEARCH_RESPONSE_JSON = {
    "response": {
        "contests": {
            "237": {
                "contestName": "U.S. Senate",
                "contestTypeCode": "FED",
                "choices": {"501": {"name": "Alice Brown", "isWriteIn": False}},
            }
        }
    }
}

_RESULTS_RESPONSE_JSON = {
    "response": {
        "contests": {
            "237": {
                "totalVotes": 1000,
                "choices": [{"choiceID": "501", "totalVotes": 1000, "votePercent": 100.0, "isWinner": True}],
            }
        }
    }
}


@pytest.mark.django_db
def test_fetch_results_no_totalvote_election_id():
    adapter = ArkansasAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = _make_election(source_metadata={})
        result = adapter.fetch_results(None, election_id=42)

    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "totalvote_election_id" in result.notes


@pytest.mark.django_db
def test_fetch_results_election_not_found():
    from elections.models import Election

    adapter = ArkansasAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.side_effect = Election.DoesNotExist
        result = adapter.fetch_results(None, election_id=99)

    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "99" in result.notes


@pytest.mark.django_db
def test_fetch_results_version_unchanged():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "b412bdef-f97a-test"}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = "2026-04-29T16:33:00Z"
        mock_get.return_value = _ver_response("2026-04-29T16:33:00Z")

        result = adapter.fetch_results(None, election_id=42)

    assert result.unchanged is True
    assert result.source_version == "2026-04-29T16:33:00Z"
    assert result.rows == []
    # Only the version check call; /download must NOT be called
    assert mock_get.call_count == 1


@pytest.mark.django_db
def test_fetch_results_guid_calls_download():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "b412bdef-f97a-45bc-b3ec-6761d28caf9e"}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(), _download_response()]

        result = adapter.fetch_results(None, election_id=42)

    assert result.mapping_confidence == "full"
    assert result.unchanged is False
    assert len(result.rows) == 2  # two candidates from _DOWNLOAD_PAYLOAD
    assert mock_get.call_count == 2
    # Second call must be to the /download path
    second_url = mock_get.call_args_list[1][0][0]
    assert "/download" in second_url
    assert "b412bdef" in second_url


@pytest.mark.django_db
def test_fetch_results_guid_official_rows():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "b412bdef-f97a-45bc-b3ec-6761d28caf9e"}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(is_official=True), _download_response()]

        result = adapter.fetch_results(None, election_id=42)

    # resultsType=certified in _DOWNLOAD_PAYLOAD → official
    assert all(r.result_type == "official" for r in result.rows)


@pytest.mark.django_db
def test_fetch_results_numeric_calls_granular():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "1846"}  # legacy numeric ID

    search_resp = MagicMock()
    search_resp.json.return_value = _SEARCH_RESPONSE_JSON
    results_resp = MagicMock()
    results_resp.json.return_value = _RESULTS_RESPONSE_JSON

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        # call order: CheckCurrentVersion, GetContestSearchList, GetContestResults?contestType=FED
        mock_get.side_effect = [_ver_response(), search_resp, results_resp]

        result = adapter.fetch_results(None, election_id=42)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 1
    assert result.rows[0].office_title == "U.S. Senate"
    assert result.rows[0].candidate_name == "Alice Brown"
    assert result.rows[0].vote_count == 1000
    assert result.rows[0].is_winner is True
    # Must NOT call /download
    urls_called = [c[0][0] for c in mock_get.call_args_list]
    assert not any("/download" in u for u in urls_called)
    assert any("GetContestSearchList" in u for u in urls_called)
    assert any("contestType=FED" in u for u in urls_called)


@pytest.mark.django_db
def test_fetch_results_numeric_official_when_is_official_true():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "1846"}

    search_resp = MagicMock()
    search_resp.json.return_value = _SEARCH_RESPONSE_JSON
    results_resp = MagicMock()
    results_resp.json.return_value = _RESULTS_RESPONSE_JSON

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(is_official=True), search_resp, results_resp]

        result = adapter.fetch_results(None, election_id=42)

    assert result.rows[0].result_type == "official"


@pytest.mark.django_db
def test_fetch_results_numeric_unofficial_when_not_official():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "1846"}

    search_resp = MagicMock()
    search_resp.json.return_value = _SEARCH_RESPONSE_JSON
    results_resp = MagicMock()
    results_resp.json.return_value = _RESULTS_RESPONSE_JSON

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(is_official=False), search_resp, results_resp]

        result = adapter.fetch_results(None, election_id=42)

    assert result.rows[0].result_type == "unofficial"


@pytest.mark.django_db
def test_fetch_results_custom_cid_used():
    adapter = ArkansasAdapter()
    meta = {
        "totalvote_cid": "custom-client",
        "totalvote_election_id": "custom-guid-1234-5678-9abc",
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(), _download_response()]

        adapter.fetch_results(None, election_id=42)

    # All requests must use the custom cId, not "arkansas"
    for c in mock_get.call_args_list:
        url = c[0][0]
        if "cId=" in url:
            assert "custom-client" in url


@pytest.mark.django_db
def test_fetch_results_http_error_propagates():
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "b412bdef-test"}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = req_lib.RequestException("timeout")

        with pytest.raises(req_lib.RequestException):
            adapter.fetch_results(None, election_id=42)


@pytest.mark.django_db
def test_fetch_results_version_not_written_by_adapter():
    """Version cache must only be written by the task, never the adapter."""
    adapter = ArkansasAdapter()
    meta = {"totalvote_election_id": "b412bdef-test"}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ar.requests.get") as mock_get, \
         patch("results.adapters.ar.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election(source_metadata=meta)
        mock_cache.get.return_value = None
        mock_get.side_effect = [_ver_response(), _download_response()]

        adapter.fetch_results(None, election_id=42)

    mock_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_ar_adapter_registered():
    import results.adapters.ar  # noqa: F401 — ensure @register runs
    from results.adapters.registry import get_adapter, list_supported_states

    assert "AR" in list_supported_states()
    assert get_adapter("AR") is ArkansasAdapter
    assert get_adapter("ar") is ArkansasAdapter


def test_version_cache_key():
    assert ArkansasAdapter.version_cache_key(42) == "totalvote:ver:42"
    assert ArkansasAdapter.version_cache_key(1) == "totalvote:ver:1"
