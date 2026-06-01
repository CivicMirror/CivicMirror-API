"""
Unit tests for the Connecticut PCC EMS results adapter.
HTTP calls and DB access are fully mocked — no network or DB required.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from results.adapters.base import AdapterResult
from results.adapters.ct import (
    ConnecticutAdapter,
    _build_office_town_map,
    _build_winner_set,
    _flatten_office_list,
    _parse_ballot_questions,
    _parse_state_votes,
    _safe_float,
    _safe_int,
)

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

def test_safe_int_plain():
    assert _safe_int(820703) == 820703


def test_safe_int_comma_string():
    assert _safe_int("820,703") == 820703


def test_safe_int_none():
    assert _safe_int(None) == 0


def test_safe_int_invalid():
    assert _safe_int("abc") == 0


def test_safe_float_plain():
    assert _safe_float(55.78) == 55.78


def test_safe_float_percent_string():
    assert _safe_float("55.78%") == pytest.approx(55.78)


def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_invalid():
    assert _safe_float("bad") is None


# ---------------------------------------------------------------------------
# _flatten_office_list
# ---------------------------------------------------------------------------

def test_flatten_office_list_basic():
    office_list = [
        {"17127": {"ID": "17127", "NM": "Mayor", "OT": "SM"}},
        {"16518": {"ID": "16518", "NM": "Presidential Electors for", "OT": "SW"}},
    ]
    result = _flatten_office_list(office_list)
    assert result["17127"]["NM"] == "Mayor"
    assert result["17127"]["OT"] == "SM"
    assert result["16518"]["OT"] == "SW"


def test_flatten_office_list_empty():
    assert _flatten_office_list([]) == {}


def test_flatten_office_list_none():
    assert _flatten_office_list(None) == {}


def test_flatten_office_list_non_dict_entry_skipped():
    office_list = [
        {"17127": {"ID": "17127", "NM": "Mayor", "OT": "SM"}},
        "not_a_dict",
    ]
    result = _flatten_office_list(office_list)
    assert len(result) == 1
    assert "17127" in result


# ---------------------------------------------------------------------------
# _build_winner_set
# ---------------------------------------------------------------------------

_GROUPING = {
    "16524": [{"35495": {"V": "1000695", "TO": "58.58%"}}],
    "16857": [{"35152": {"V": "208649", "TO": "63.14%"}}],
}


def test_build_winner_set_pairs():
    pairs, offices = _build_winner_set(_GROUPING)
    assert ("16524", "35495") in pairs
    assert ("16857", "35152") in pairs


def test_build_winner_set_offices():
    _, offices = _build_winner_set(_GROUPING)
    assert "16524" in offices
    assert "16857" in offices


def test_build_winner_set_loser_not_in_pairs():
    pairs, _ = _build_winner_set(_GROUPING)
    assert ("16524", "99999") not in pairs


def test_build_winner_set_empty():
    pairs, offices = _build_winner_set({})
    assert pairs == set()
    assert offices == set()


def test_build_winner_set_none():
    pairs, offices = _build_winner_set(None)
    assert pairs == set()
    assert offices == set()


# ---------------------------------------------------------------------------
# _build_office_town_map
# ---------------------------------------------------------------------------

_TOWN_VOTES = {
    "2": {"17127": [{"36347": {"V": "5290", "TO": "55.78%"}}]},  # Ansonia → SM Mayor
    "4": {"17171": [{"37000": {"V": "3200", "TO": "60.00%"}}]},  # Avon → SM Mayor
    # officeID 99999 appears in two towns → multi-town, excluded
    "5": {"99999": []},
    "6": {"99999": []},
    # officeID 88888 is single-town but non-SM → excluded
    "2": {"17127": [{"36347": {"V": "5290", "TO": "55.78%"}}], "88888": []},
}

_TOWN_IDS = {"2": "Ansonia", "4": "Avon", "5": "Barkhamsted", "6": "Berlin"}

_OFFICE_MAP_WITH_TYPES = {
    "17127": {"ID": "17127", "NM": "Mayor", "OT": "SM"},
    "17171": {"ID": "17171", "NM": "Mayor", "OT": "SM"},
    "88888": {"ID": "88888", "NM": "State Representative 1", "OT": "A"},
    "99999": {"ID": "99999", "NM": "State Senator", "OT": "SEN"},
}


def test_build_office_town_map_sm_single_town():
    tv = {"2": {"17127": []}}
    result = _build_office_town_map(tv, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES)
    assert result["17127"] == "Ansonia"


def test_build_office_town_map_multi_town_excluded():
    tv = {"5": {"99999": []}, "6": {"99999": []}}
    result = _build_office_town_map(tv, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES)
    assert "99999" not in result


def test_build_office_town_map_non_sm_single_town_excluded():
    # OT="A" office that happens to be in only one town must NOT get a town prefix
    tv = {"2": {"88888": []}}
    result = _build_office_town_map(tv, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES)
    assert "88888" not in result


def test_build_office_town_map_empty_town_votes():
    assert _build_office_town_map({}, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES) == {}


def test_build_office_town_map_none():
    assert _build_office_town_map(None, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES) == {}


def test_build_office_town_map_unknown_town_id_excluded():
    tv = {"999": {"17127": []}}  # townID 999 not in _TOWN_IDS
    result = _build_office_town_map(tv, _TOWN_IDS, _OFFICE_MAP_WITH_TYPES)
    assert "17127" not in result


# ---------------------------------------------------------------------------
# _parse_state_votes
# ---------------------------------------------------------------------------

_OFFICE_MAP = {
    "16524": {"ID": "16524", "NM": "United States Senator", "OT": "SW"},
    "16518": {"ID": "16518", "NM": "Presidential Electors for", "OT": "SW"},
}

_CANDIDATE_MAP = {
    "35495": {"NM": "Christopher S. Murphy", "LN": "Murphy", "FN": "Christopher", "P": "1"},
    "35830": {"NM": "Matthew M. Corey", "LN": "Corey", "FN": "Matthew", "P": "6"},
    "35838": {"NM": "Harris and Walz", "LN": "Harris", "FN": "Kamala", "P": "1"},
    "35839": {"NM": "Trump and Vance", "LN": "Trump", "FN": "Donald", "P": "6"},
    "42781": {"NM": ".", "LN": ".", "FN": ".", "P": "1"},  # anonymized — must be skipped
}

_STATE_VOTES = {
    "16524": [
        {"35495": {"V": "953,646", "TO": "55.83%"}},
        {"35830": {"V": "678,256", "TO": "39.70%"}},
    ],
    "16518": [
        {"35838": {"V": "992,053", "TO": "56.40%"}},
        {"35839": {"V": "736,918", "TO": "41.89%"}},
    ],
}


def test_parse_state_votes_row_count():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    assert len(rows) == 4


def test_parse_state_votes_office_title():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    senate_rows = [r for r in rows if r.office_title == "United States Senator"]
    assert len(senate_rows) == 2


def test_parse_state_votes_candidate_name():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    senate_rows = [r for r in rows if r.office_title == "United States Senator"]
    names = {r.candidate_name for r in senate_rows}
    assert "Christopher S. Murphy" in names
    assert "Matthew M. Corey" in names


def test_parse_state_votes_vote_count_comma_stripped():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    murphy = next(r for r in rows if r.candidate_name == "Christopher S. Murphy")
    assert murphy.vote_count == 953646


def test_parse_state_votes_vote_pct():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    murphy = next(r for r in rows if r.candidate_name == "Christopher S. Murphy")
    assert murphy.vote_pct == pytest.approx(55.83)


def test_parse_state_votes_winner_true_for_grouping_candidate():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    murphy = next(r for r in rows if r.candidate_name == "Christopher S. Murphy")
    assert murphy.is_winner is True


def test_parse_state_votes_winner_false_for_loser():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    corey = next(r for r in rows if r.candidate_name == "Matthew M. Corey")
    assert corey.is_winner is False


def test_parse_state_votes_winner_none_for_office_absent_from_grouping():
    # Presidential race (16518) is NOT in _GROUPING → is_winner should be None
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    pres_rows = [r for r in rows if r.office_title == "Presidential Electors for"]
    assert all(r.is_winner is None for r in pres_rows)


def test_parse_state_votes_winner_none_when_vote_count_zero():
    # candidateGrouping may have placeholder entries before votes exist;
    # is_winner must be None (not True/False) when vote_count == 0.
    grouping = {"16524": [{"35495": {"V": "0", "TO": "0.00%"}}]}
    pairs, offices = _build_winner_set(grouping)
    sv = {"16524": [
        {"35495": {"V": "0", "TO": "0.00%"}},
        {"35830": {"V": "0", "TO": "0.00%"}},
    ]}
    rows = _parse_state_votes(sv, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official")
    assert all(r.is_winner is None for r in rows)


def test_parse_state_votes_result_type():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    assert all(r.result_type == "official" for r in rows)


def test_parse_state_votes_unofficial_result_type():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        _STATE_VOTES, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "unofficial",
    )
    assert all(r.result_type == "unofficial" for r in rows)


def test_parse_state_votes_dot_candidate_skipped():
    sv = {"16524": [{"42781": {"V": "0", "TO": "0.00%"}}]}
    pairs, offices = _build_winner_set({})
    rows = _parse_state_votes(sv, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official")
    assert rows == []


def test_parse_state_votes_empty():
    pairs, offices = _build_winner_set({})
    rows = _parse_state_votes({}, _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official")
    assert rows == []


def test_parse_state_votes_municipal_title_qualified_with_town():
    municipal_office_map = {"17127": {"ID": "17127", "NM": "Mayor", "OT": "SM"}}
    municipal_candidate_map = {"36347": {"NM": "Jane Smith", "P": "1"}}
    sv = {"17127": [{"36347": {"V": "5290", "TO": "55.78%"}}]}
    office_town_map = {"17127": "Ansonia"}

    pairs, offices = _build_winner_set({})
    rows = _parse_state_votes(
        sv, municipal_office_map, municipal_candidate_map,
        pairs, offices, office_town_map, "official",
    )
    assert rows[0].office_title == "Ansonia — Mayor"
    assert rows[0].jurisdiction_fragment == "Ansonia"


def test_parse_state_votes_statewide_title_unqualified():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        {"16524": [{"35495": {"V": "100", "TO": "55%"}}]},
        _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    assert rows[0].office_title == "United States Senator"
    assert rows[0].jurisdiction_fragment == ""


def test_parse_state_votes_raw_contains_office_id():
    pairs, offices = _build_winner_set(_GROUPING)
    rows = _parse_state_votes(
        {"16524": [{"35495": {"V": "100", "TO": "100.0%"}}]},
        _OFFICE_MAP, _CANDIDATE_MAP, pairs, offices, {}, "official",
    )
    assert rows[0].raw["officeID"] == "16524"
    assert rows[0].raw["candidateID"] == "35495"
    assert rows[0].raw["OT"] == "SW"


# ---------------------------------------------------------------------------
# _parse_ballot_questions
# ---------------------------------------------------------------------------

_TOWN_NAME_SET = {"Andover", "Bethany", "Bethel", "Avon"}

_BALLOT_DATA = {
    "State Wide": [
        {
            "QN": "Shall the Constitution of Connecticut be amended?",
            "YES": "843,153",
            "NO": "610,694",
            "NTH": "-",
            "NTL": "-",
        }
    ],
    "Bethany": [
        {"QN": "Shall the sale of alcoholic liquor be allowed?", "YES": "1747", "NO": "498", "NTH": "-", "NTL": "-"}
    ],
    "Unknown_Key": [  # not in town_name_set → skipped
        {"QN": "Ignore me", "YES": "100", "NO": "50", "NTH": "-", "NTL": "-"}
    ],
}


def test_parse_ballot_questions_statewide_produces_two_rows():
    rows = _parse_ballot_questions({"State Wide": _BALLOT_DATA["State Wide"]}, _TOWN_NAME_SET, "official")
    assert len(rows) == 2


def test_parse_ballot_questions_option_labels():
    rows = _parse_ballot_questions({"State Wide": _BALLOT_DATA["State Wide"]}, _TOWN_NAME_SET, "official")
    labels = {r.option_label for r in rows}
    assert labels == {"YES", "NO"}


def test_parse_ballot_questions_statewide_vote_counts():
    rows = _parse_ballot_questions({"State Wide": _BALLOT_DATA["State Wide"]}, _TOWN_NAME_SET, "official")
    yes_row = next(r for r in rows if r.option_label == "YES")
    no_row = next(r for r in rows if r.option_label == "NO")
    assert yes_row.vote_count == 843153
    assert no_row.vote_count == 610694


def test_parse_ballot_questions_statewide_no_fragment():
    rows = _parse_ballot_questions({"State Wide": _BALLOT_DATA["State Wide"]}, _TOWN_NAME_SET, "official")
    assert all(r.jurisdiction_fragment == "" for r in rows)


def test_parse_ballot_questions_town_question_included():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "official")
    town_rows = [r for r in rows if r.jurisdiction_fragment == "Bethany"]
    assert len(town_rows) == 2
    assert all("Bethany" in (r.office_title or "") for r in town_rows)


def test_parse_ballot_questions_town_question_title_qualified():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "official")
    town_rows = [r for r in rows if r.jurisdiction_fragment == "Bethany"]
    yes_row = next(r for r in town_rows if r.option_label == "YES")
    assert yes_row.office_title.startswith("Bethany — ")


def test_parse_ballot_questions_unknown_key_skipped():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "official")
    # Unknown_Key should produce 0 rows
    assert all("Ignore" not in (r.office_title or "") for r in rows)


def test_parse_ballot_questions_candidate_name_is_none():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "official")
    assert all(r.candidate_name is None for r in rows)


def test_parse_ballot_questions_is_winner_is_none():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "official")
    assert all(r.is_winner is None for r in rows)


def test_parse_ballot_questions_result_type():
    rows = _parse_ballot_questions(_BALLOT_DATA, _TOWN_NAME_SET, "unofficial")
    assert all(r.result_type == "unofficial" for r in rows)


def test_parse_ballot_questions_dash_value_skipped():
    data = {"State Wide": [{"QN": "Q", "YES": "-", "NO": "100", "NTH": "-", "NTL": "-"}]}
    rows = _parse_ballot_questions(data, _TOWN_NAME_SET, "official")
    assert len(rows) == 1
    assert rows[0].option_label == "NO"


def test_parse_ballot_questions_empty():
    assert _parse_ballot_questions({}, _TOWN_NAME_SET, "official") == []


# ---------------------------------------------------------------------------
# ConnecticutAdapter.fetch_results — mocked integration tests
# ---------------------------------------------------------------------------

def _make_election(source_metadata=None):
    e = MagicMock()
    e.pk = 7
    e.source_id = "ct_elect_test"
    e.source_metadata = source_metadata or {}
    return e


def _ver_resp(version=70782):
    m = MagicMock()
    m.json.return_value = {"Version": version}
    return m


def _reports_resp(is_official=True):
    m = MagicMock()
    m.json.return_value = {"IR": "True", "IO": "True" if is_official else "False"}
    return m


def _lookup_resp():
    m = MagicMock()
    m.json.return_value = {
        "election": {"ID": "91", "NM": "Test Election"},
        "officeList": [
            {"16524": {"ID": "16524", "NM": "United States Senator", "OT": "SW"}},
        ],
        "candidateIds": {
            "35495": {"NM": "Christopher S. Murphy", "P": "1"},
            "35830": {"NM": "Matthew M. Corey", "P": "6"},
        },
        "partyIds": {"1": {"CD": "D", "NM": "Democratic Party"}, "6": {"CD": "R", "NM": "Republican Party"}},
        "townIds": {"1": "Andover", "2": "Ansonia"},
    }
    return m


def _state_votes_resp():
    m = MagicMock()
    m.json.return_value = {
        "16524": [
            {"35495": {"V": "953646", "TO": "55.83%"}},
            {"35830": {"V": "678256", "TO": "39.70%"}},
        ]
    }
    return m


def _grouping_resp():
    m = MagicMock()
    m.json.return_value = {"16524": [{"35495": {"V": "953646", "TO": "55.83%"}}]}
    return m


def _ballot_resp(empty=False, with_town=False):
    m = MagicMock()
    if empty:
        m.json.return_value = {}
    elif with_town:
        m.json.return_value = {
            "Andover": [{"QN": "Local question", "YES": "200", "NO": "100", "NTH": "-", "NTL": "-"}]
        }
    else:
        m.json.return_value = {
            "State Wide": [{"QN": "Amendment?", "YES": "843153", "NO": "610694", "NTH": "-", "NTL": "-"}]
        }
    return m


def _town_votes_resp():
    m = MagicMock()
    # officeID 16524 in both towns → multi-town, excluded from office_town_map
    m.json.return_value = {
        "1": {"16524": [{"35495": {"V": "1000", "TO": "55%"}}]},
        "2": {"16524": [{"35495": {"V": "2000", "TO": "55%"}}]},
    }
    return m


def _full_side_effect(version=70782, is_official=True, empty_ballot=False, town_ballot=False):
    return [
        _ver_resp(version),
        _reports_resp(is_official),
        _lookup_resp(),
        _state_votes_resp(),
        _grouping_resp(),
        _ballot_resp(empty_ballot, town_ballot),
        _town_votes_resp(),
    ]


@pytest.mark.django_db
def test_fetch_results_no_ct_election_id():
    adapter = ConnecticutAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = _make_election(source_metadata={})
        result = adapter.fetch_results(None, election_id=7)

    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "ct_election_id" in result.notes


@pytest.mark.django_db
def test_fetch_results_election_not_found():
    from elections.models import Election

    adapter = ConnecticutAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.side_effect = Election.DoesNotExist
        result = adapter.fetch_results(None, election_id=99)

    assert result.mapping_confidence == "none"
    assert "99" in result.notes


@pytest.mark.django_db
def test_fetch_results_version_unchanged():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = "70782"
        mock_get.return_value = _ver_resp(70782)

        result = adapter.fetch_results(None, election_id=7)

    assert result.unchanged is True
    assert result.source_version == "70782"
    assert result.rows == []
    assert mock_get.call_count == 1


@pytest.mark.django_db
def test_fetch_results_full_official():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect(is_official=True)

        result = adapter.fetch_results(None, election_id=7)

    assert result.mapping_confidence == "full"
    assert result.unchanged is False
    assert result.source_version == "70782"
    assert len(result.rows) == 4  # 2 candidate rows + 2 ballot YES/NO rows
    assert all(r.result_type == "official" for r in result.rows)


@pytest.mark.django_db
def test_fetch_results_unofficial_result_type():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect(is_official=False)

        result = adapter.fetch_results(None, election_id=7)

    assert all(r.result_type == "unofficial" for r in result.rows)


@pytest.mark.django_db
def test_fetch_results_candidate_rows_correct():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect()

        result = adapter.fetch_results(None, election_id=7)

    cand_rows = [r for r in result.rows if r.candidate_name is not None]
    assert len(cand_rows) == 2
    murphy = next(r for r in cand_rows if r.candidate_name == "Christopher S. Murphy")
    assert murphy.vote_count == 953646
    assert murphy.vote_pct == pytest.approx(55.83)
    assert murphy.is_winner is True
    assert murphy.office_title == "United States Senator"


@pytest.mark.django_db
def test_fetch_results_ballot_rows_correct():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect()

        result = adapter.fetch_results(None, election_id=7)

    bq_rows = [r for r in result.rows if r.option_label is not None]
    assert len(bq_rows) == 2
    yes_row = next(r for r in bq_rows if r.option_label == "YES")
    assert yes_row.vote_count == 843153
    assert yes_row.candidate_name is None
    assert yes_row.is_winner is None


@pytest.mark.django_db
def test_fetch_results_town_ballot_questions_included():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "97"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect(town_ballot=True)

        result = adapter.fetch_results(None, election_id=7)

    bq_rows = [r for r in result.rows if r.option_label is not None]
    # town "Andover" is in townIds → 2 rows (YES+NO)
    assert len(bq_rows) == 2
    assert all(r.jurisdiction_fragment == "Andover" for r in bq_rows)
    assert all("Andover" in (r.office_title or "") for r in bq_rows)


@pytest.mark.django_db
def test_fetch_results_no_ballot_questions():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "97"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect(empty_ballot=True)

        result = adapter.fetch_results(None, election_id=7)

    assert all(r.option_label is None for r in result.rows)


@pytest.mark.django_db
def test_fetch_results_version_not_written_by_adapter():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect()

        adapter.fetch_results(None, election_id=7)

    mock_cache.set.assert_not_called()


@pytest.mark.django_db
def test_fetch_results_http_error_propagates():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = req_lib.RequestException("timeout")

        with pytest.raises(req_lib.RequestException):
            adapter.fetch_results(None, election_id=7)


@pytest.mark.django_db
def test_fetch_results_seven_http_calls_on_full_fetch():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect()

        adapter.fetch_results(None, election_id=7)

    assert mock_get.call_count == 7


@pytest.mark.django_db
def test_fetch_results_source_url_is_state_votes():
    adapter = ConnecticutAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.ct.requests.get") as mock_get, \
         patch("results.adapters.ct.cache") as mock_cache:

        mock_mgr.get.return_value = _make_election({"ct_election_id": "91"})
        mock_cache.get.return_value = None
        mock_get.side_effect = _full_side_effect()

        result = adapter.fetch_results(None, election_id=7)

    assert "stateVotes_Electiondata.json" in result.source_url


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_ct_adapter_registered():
    import results.adapters.ct  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "CT" in list_supported_states()
    assert get_adapter("CT") is ConnecticutAdapter
    assert get_adapter("ct") is ConnecticutAdapter


def test_version_cache_key():
    assert ConnecticutAdapter.version_cache_key(7) == "ct_elect:ver:7"
    assert ConnecticutAdapter.version_cache_key(91) == "ct_elect:ver:91"
