"""
Unit tests for the Alaska ENR precinct-results adapter.

HTTP calls are mocked — no network required. See issue #233: the previous
`AlaskaAdapter(ClarityAdapter)` never made any HTTP request because Alaska
isn't a Clarity state; this adapter replaces it with a real CSV fetch
against Alaska's own ENR export, with a pinned TLS intermediate (the same
technique used for AL SOS, #132) to work around Alaska's broken cert chain.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from results.adapters.ak import (
    AlaskaAdapter,
    _AlaskaChainFixAdapter,
    _build_session,
    _office_title,
    _reverse_name,
)
from results.models import OfficialResult

# A trimmed two-precinct slice of the live schema: one candidate contest
# (U.S. Senator, three precincts worth of votes to sum), a State House
# district contest, a Governor/Lt. Governor ticket, and one judicial
# retention contest (YES/NO) that must be excluded.
SAMPLE_CSV = (
    "Precinct_name,Reporting_flag,Pct_Id,Contest_title,candidate_name,total_votes\r\n"
    '"Precinct A",1,"01-010","U.S. Senator","Sullivan, Dan S.",120\r\n'
    '"Precinct A",1,"01-010","U.S. Senator","Peltola, Mary",80\r\n'
    '"Precinct B",1,"01-020","U.S. Senator","Sullivan, Dan S.",200\r\n'
    '"Precinct B",1,"01-020","U.S. Senator","Peltola, Mary",150\r\n'
    '"Precinct A",1,"01-010","House District 1","Jeremy T. Bynum",90\r\n'
    '"Precinct A",1,"01-010","Governor / Lieutenant Governor","Bronson/Church",60\r\n'
    '"Precinct A",1,"01-010","Supreme Court - Pate","YES",40\r\n'
    '"Precinct A",1,"01-010","Supreme Court - Pate","NO",10\r\n'
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_office_title_renames_house_district():
    assert _office_title("House District 1") == "State House - District 1"


def test_office_title_renames_senate_district():
    assert _office_title("Senate District C") == "State Senate - District C"


def test_office_title_leaves_other_titles_unchanged():
    assert _office_title("U.S. Senator") == "U.S. Senator"
    assert _office_title("U.S. Representative") == "U.S. Representative"
    assert _office_title("Governor / Lieutenant Governor") == "Governor / Lieutenant Governor"


def test_reverse_name_simple():
    assert _reverse_name("Sullivan, Dan S.") == "Dan S. Sullivan"


def test_reverse_name_with_suffix():
    assert _reverse_name("Sullivan, Daniel J. Jr.") == "Daniel J. Jr. Sullivan"


def test_reverse_name_no_comma_passthrough():
    # Governor/Lt. Governor tickets have no comma; left as the source gives it.
    assert _reverse_name("Bronson/Church") == "Bronson/Church"


# ---------------------------------------------------------------------------
# AlaskaAdapter._parse_csv
# ---------------------------------------------------------------------------

def test_parse_csv_sums_votes_across_precincts():
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    by_candidate = {r.candidate_name: r.vote_count for r in rows if r.office_title == "U.S. Senator"}
    assert by_candidate["Dan S. Sullivan"] == 320
    assert by_candidate["Mary Peltola"] == 230


def test_parse_csv_excludes_yes_no_judicial_retention():
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    names = {r.candidate_name for r in rows}
    assert "YES" not in names
    assert "NO" not in names
    assert not any(r.office_title == "Supreme Court - Pate" for r in rows)


def test_parse_csv_renames_district_offices():
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    titles = {r.office_title for r in rows}
    assert "State House - District 1" in titles
    assert "House District 1" not in titles


def test_parse_csv_governor_ticket_passthrough():
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    governor_rows = [r for r in rows if r.office_title == "Governor / Lieutenant Governor"]
    assert len(governor_rows) == 1
    assert governor_rows[0].candidate_name == "Bronson/Church"


def test_parse_csv_result_type_always_unofficial():
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    assert all(r.result_type == OfficialResult.ResultType.UNOFFICIAL for r in rows)


def test_parse_csv_never_sets_is_winner():
    # AK general races are decided by ranked-choice instant runoff; this feed
    # is first-choice-only, so no row may claim a winner.
    rows = AlaskaAdapter._parse_csv(SAMPLE_CSV.encode("utf-8"))
    assert all(r.is_winner is None for r in rows)


def test_parse_csv_decodes_bom():
    bom_csv = "﻿" + SAMPLE_CSV
    rows = AlaskaAdapter._parse_csv(bom_csv.encode("utf-8-sig"))
    assert len(rows) > 0


# ---------------------------------------------------------------------------
# AlaskaAdapter.fetch_results — integration with mocked HTTP + DB
# ---------------------------------------------------------------------------

def _make_election(election_type="general", election_date_=date(2026, 11, 3)):
    from elections.models import Election

    return Election.objects.create(
        source_id=f"ak_{election_type}_2026",
        name="2026 Alaska Election",
        state="AK",
        election_type=election_type,
        election_date=election_date_,
        status="upcoming",
        jurisdiction_level="state",
    )


def _mock_response(content: bytes) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.django_db
def test_fetch_results_builds_general_url():
    election = _make_election(election_type="general", election_date_=date(2026, 11, 3))

    with patch("results.adapters.ak.cache") as mock_cache, \
         patch("results.adapters.ak.requests.Session.get") as mock_get:
        mock_cache.get.return_value = None
        mock_get.return_value = _mock_response(SAMPLE_CSV.encode("utf-8"))

        result = AlaskaAdapter().fetch_results(election.election_date, election.pk)

    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://www.elections.alaska.gov/enr/26GENR/results/GA_ENR_Precinct_State_of_Alaska.csv"
    )
    assert result.mapping_confidence == "full"
    assert len(result.rows) > 0


@pytest.mark.django_db
def test_fetch_results_builds_primary_url():
    election = _make_election(election_type="primary", election_date_=date(2026, 8, 18))

    with patch("results.adapters.ak.cache") as mock_cache, \
         patch("results.adapters.ak.requests.Session.get") as mock_get:
        mock_cache.get.return_value = None
        mock_get.return_value = _mock_response(SAMPLE_CSV.encode("utf-8"))

        AlaskaAdapter().fetch_results(election.election_date, election.pk)

    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://www.elections.alaska.gov/enr/26PRIM/results/GA_ENR_Precinct_State_of_Alaska.csv"
    )


@pytest.mark.django_db
def test_fetch_results_unsupported_election_type_makes_no_request():
    election = _make_election(election_type="special", election_date_=date(2026, 11, 3))

    with patch("results.adapters.ak.requests.Session.get") as mock_get:
        result = AlaskaAdapter().fetch_results(election.election_date, election.pk)

    mock_get.assert_not_called()
    assert result.mapping_confidence == "none"
    assert "special" in result.notes


def test_build_session_mounts_chain_fix_adapter_for_ak_host_only():
    """
    Regression test for #233: www.elections.alaska.gov omits its GlobalSign
    intermediate during the TLS handshake, so AlaskaAdapter must route
    requests to that host through the adapter that supplies the missing
    intermediate — and only that host, so a real cert problem elsewhere
    wouldn't get masked (same convention as AL SOS, #132).
    """
    session = _build_session()

    ak_adapter = session.get_adapter("https://www.elections.alaska.gov/anything")
    other_adapter = session.get_adapter("https://example.com/anything")
    assert isinstance(ak_adapter, _AlaskaChainFixAdapter)
    assert not isinstance(other_adapter, _AlaskaChainFixAdapter)


@pytest.mark.django_db
def test_fetch_results_version_unchanged_short_circuits():
    election = _make_election()
    content = SAMPLE_CSV.encode("utf-8")
    import hashlib
    current_ver = hashlib.sha256(content).hexdigest()

    with patch("results.adapters.ak.cache") as mock_cache, \
         patch("results.adapters.ak.requests.Session.get") as mock_get:
        mock_cache.get.return_value = current_ver
        mock_get.return_value = _mock_response(content)

        result = AlaskaAdapter().fetch_results(election.election_date, election.pk)

    assert result.unchanged is True
    assert result.rows == []
    assert result.source_version == current_ver


@pytest.mark.django_db
def test_fetch_results_new_version_parses_rows():
    election = _make_election()
    content = SAMPLE_CSV.encode("utf-8")

    with patch("results.adapters.ak.cache") as mock_cache, \
         patch("results.adapters.ak.requests.Session.get") as mock_get:
        mock_cache.get.return_value = "stale-version"
        mock_get.return_value = _mock_response(content)

        result = AlaskaAdapter().fetch_results(election.election_date, election.pk)

    assert result.unchanged is False
    assert len(result.rows) > 0
    mock_cache.set.assert_not_called()  # adapter itself never writes the cache


@pytest.mark.django_db
def test_fetch_results_election_not_found():
    with patch("results.adapters.ak.requests.Session.get") as mock_get:
        result = AlaskaAdapter().fetch_results(date(2026, 11, 3), 999999)

    mock_get.assert_not_called()
    assert result.mapping_confidence == "none"
    assert "not found" in result.notes


@pytest.mark.django_db
def test_fetch_results_http_error_propagates():
    election = _make_election()

    with patch("results.adapters.ak.cache") as mock_cache, \
         patch("results.adapters.ak.requests.Session.get") as mock_get:
        mock_cache.get.return_value = None
        mock_get.side_effect = req_lib.RequestException("boom")

        with pytest.raises(req_lib.RequestException):
            AlaskaAdapter().fetch_results(election.election_date, election.pk)
