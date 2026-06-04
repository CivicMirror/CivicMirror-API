"""
Unit tests for the Arizona SOS results adapter.
HTTP calls are mocked; no network access required.
"""
import textwrap
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.az import (
    ArizonaAdapter,
    _build_url,
    _derive_election_name,
    _parse_results,
    _safe_int,
)

# ---------------------------------------------------------------------------
# Shared test XML
# ---------------------------------------------------------------------------

_SAMPLE_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <electionResult>
      <electionInformation>
        <resultsTimestamp>2026-07-21T20:15:00.000</resultsTimestamp>
        <electionName>2026 Primary Election</electionName>
        <electionDate>2026-07-21</electionDate>
        <fileId>12500</fileId>
      </electionInformation>
      <voterTurnout>
        <jurisdictions>
          <jurisdiction key="0" name="State" totalVoters="4200000"
              ballotsCast="1400000" voterTurnout="33.33"
              precinctsParticipating="1800" precinctsReported="1800"
              precinctsReportingPercent="100.00"
              earlyBallotsRemaining="0" provisionalBallotsRemaining="0"
              ballotsReadyToProcess="0" ballotsRemaining="0"
              ballotProcessingCompletedPercentage="100.00" />
        </jurisdictions>
      </voterTurnout>
      <contests>
        <contest key="100" contestLongName="U.S. Senator (DEM)"
                 districtKey="1" districtName="Federal Statewide"
                 numberToElect="1" termYears="6" isQuestion="false"
                 countiesParticipating="15" countiesReported="15"
                 precinctsParticipating="1800" precinctsReported="1800"
                 precinctsReportingPercent="100.00">
          <choices>
            <choice key="200" choiceName="Smith, Jane" partyKey="3"
                    party="DEM" totalVotes="400000" isWriteIn="false" />
            <choice key="201" choiceName="Jones, Bob" partyKey="3"
                    party="DEM" totalVotes="300000" isWriteIn="false" />
            <choice key="202" choiceName="Write-In" partyKey="1"
                    party="IND" totalVotes="500" isWriteIn="true" />
          </choices>
          <jurisdictions>
            <jurisdiction key="0" name="State" votes="700500">
              <voteTypes>
                <voteType voteTypeName="Polling Place" votes="50000" />
                <voteType voteTypeName="Early Ballots" votes="650000" />
              </voteTypes>
            </jurisdiction>
          </jurisdictions>
        </contest>
        <contest key="101"
                 contestLongName="Shall Justice X be retained in office?"
                 districtKey="42" districtName="AZ Supreme Court"
                 termYears="0" isQuestion="true"
                 countiesParticipating="15" countiesReported="15"
                 precinctsParticipating="1800" precinctsReported="1800"
                 precinctsReportingPercent="100.00">
          <choices>
            <choice choiceName="Yes" totalVotes="800000" isWriteIn="false" />
            <choice choiceName="No" totalVotes="600000" isWriteIn="false" />
          </choices>
        </contest>
      </contests>
    </electionResult>
""").encode()


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

def test_safe_int_integer():
    assert _safe_int(42) == 42

def test_safe_int_string():
    assert _safe_int("498927") == 498927

def test_safe_int_comma_string():
    assert _safe_int("1,190,172") == 1190172

def test_safe_int_none():
    assert _safe_int(None) == 0

def test_safe_int_invalid():
    assert _safe_int("n/a") == 0


# ---------------------------------------------------------------------------
# _parse_results
# ---------------------------------------------------------------------------

def test_parse_results_returns_file_id():
    file_id, _ = _parse_results(_SAMPLE_XML)
    assert file_id == "12500"

def test_parse_results_candidate_contest_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    candidate_rows = [r for r in rows if r.candidate_name is not None]
    assert len(candidate_rows) == 2  # Smith, Jones — Write-In has candidate_name=None

def test_parse_results_candidate_name_inverted():
    # XML "Last, First" must be stored as "First Last" to match Candidate.name from Stage 1
    _, rows = _parse_results(_SAMPLE_XML)
    smith = next(r for r in rows if r.candidate_name == "Jane Smith")
    assert smith.office_title == "U.S. Senator"   # party suffix stripped
    assert smith.option_label is None
    assert smith.vote_count == 400000
    assert smith.vote_pct is None
    assert smith.is_winner is None
    assert smith.result_type == "unofficial"
    assert smith.is_write_in_aggregate is False

def test_parse_results_write_in_generic_has_no_candidate_name():
    # Generic "Write-In" aggregate: candidate_name=None, attaches at race level
    _, rows = _parse_results(_SAMPLE_XML)
    write_in = next(r for r in rows if r.is_write_in_aggregate and r.candidate_name is None)
    assert write_in.vote_count == 500
    assert write_in.office_title == "U.S. Senator"

def test_parse_results_ballot_question_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    measure_rows = [r for r in rows if r.option_label is not None]
    assert len(measure_rows) == 2  # Yes + No

def test_parse_results_ballot_question_fields():
    _, rows = _parse_results(_SAMPLE_XML)
    yes_row = next(r for r in rows if r.option_label == "Yes")
    assert yes_row.candidate_name is None
    # Ballot question titles have no party suffix; normalize_contest_name is a no-op
    assert yes_row.office_title == "Shall Justice X be retained in office?"
    assert yes_row.vote_count == 800000
    assert yes_row.result_type == "unofficial"
    assert yes_row.is_write_in_aggregate is False

def test_parse_results_total_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    assert len(rows) == 5  # 2 candidates + 1 write-in aggregate + 2 ballot options

def test_parse_results_raw_contest_key():
    _, rows = _parse_results(_SAMPLE_XML)
    smith = next(r for r in rows if r.candidate_name == "Jane Smith")  # inverted
    assert smith.raw["contestKey"] == "100"
    assert smith.raw["choiceKey"] == "200"

def test_parse_results_question_no_choice_key():
    # Ballot question choices have no key attribute — raw should not raise
    _, rows = _parse_results(_SAMPLE_XML)
    yes_row = next(r for r in rows if r.option_label == "Yes")
    assert yes_row.raw.get("choiceKey", "") == ""

def test_parse_results_empty_contests():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<electionResult>
  <electionInformation>
    <fileId>99</fileId>
  </electionInformation>
  <contests />
</electionResult>"""
    file_id, rows = _parse_results(xml)
    assert file_id == "99"
    assert rows == []

def test_parse_results_missing_file_id():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<electionResult>
  <electionInformation />
  <contests />
</electionResult>"""
    file_id, rows = _parse_results(xml)
    assert file_id == ""
    assert rows == []

def test_parse_results_office_title_normalized():
    """contestLongName party suffix must be stripped so title matches Stage 1 Race records."""
    xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="utf-8"?>
        <electionResult>
          <electionInformation><fileId>1</fileId></electionInformation>
          <contests>
            <contest key="1" contestLongName="Governor (DEM)" isQuestion="false">
              <choices>
                <choice key="1" choiceName="Hobbs, Katie" party="DEM" totalVotes="100" isWriteIn="false"/>
              </choices>
            </contest>
          </contests>
        </electionResult>
    """).encode()
    _, rows = _parse_results(xml)
    assert rows[0].office_title == "Governor"       # party suffix stripped
    assert rows[0].candidate_name == "Katie Hobbs"  # "Last, First" → "First Last"


# ---------------------------------------------------------------------------
# _derive_election_name / _build_url
# ---------------------------------------------------------------------------

def _make_election(election_type: str, year: int, source_metadata: dict | None = None):
    """Build a minimal mock election object for URL tests."""
    m = MagicMock()
    m.election_date = date(year, 7, 21)
    m.election_type = election_type
    m.source_metadata = source_metadata or {}
    return m


def test_derive_election_name_primary():
    e = _make_election("primary", 2026)
    assert _derive_election_name(e) == "2026 Primary Election"


def test_derive_election_name_general():
    e = _make_election("general", 2026)
    assert _derive_election_name(e) == "2026 General Election"


def test_derive_election_name_presidential_preference():
    e = _make_election("presidential_preference", 2024)
    assert _derive_election_name(e) == "2024 Presidential Preference Election"


def test_derive_election_name_unknown_type():
    e = _make_election("runoff", 2026)
    assert _derive_election_name(e) == "2026 Runoff Election"


def test_build_url_derived():
    e = _make_election("primary", 2026)
    url = _build_url(e)
    assert url == "https://apps.azsos.gov/ftp/ElectionResults/2026/State/2026%20Primary%20Election/Results.Summary.xml"


def test_build_url_source_metadata_override():
    e = _make_election("primary", 2026, {"az_election_name": "2026 Primary Election Special"})
    url = _build_url(e)
    assert "2026%20Primary%20Election%20Special" in url


def test_build_url_spaces_encoded():
    e = _make_election("general", 2026)
    url = _build_url(e)
    assert " " not in url
    assert "%20" in url


# ---------------------------------------------------------------------------
# ArizonaAdapter.fetch_results — mocked HTTP
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_election(db):
    from elections.models import Election
    return Election.objects.create(
        name="2026 Arizona Primary Election",
        state="AZ",
        election_date=date(2026, 7, 21),
        election_type="primary",
        source_id="az_sos_2026_primary",
        status=Election.Status.RESULTS_PENDING,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        source_metadata={},
    )


@pytest.mark.django_db
def test_fetch_results_returns_rows(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert len(result.rows) == 5
    assert result.mapping_confidence == "full"
    assert result.unchanged is False


@pytest.mark.django_db
def test_fetch_results_unchanged_on_second_call(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result1 = adapter.fetch_results(mock_election.election_date, mock_election.pk)
        assert result1.source_version == "12500"
        from django.core.cache import cache
        cache.set(adapter.version_cache_key(mock_election.pk), result1.source_version)
        result2 = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert result2.unchanged is True
    assert result2.rows == []


@pytest.mark.django_db
def test_fetch_results_missing_election():
    adapter = ArizonaAdapter()
    result = adapter.fetch_results(date(2026, 7, 21), election_id=999999)
    assert result.mapping_confidence == "none"
    assert "not found" in result.notes


@pytest.mark.django_db
def test_fetch_results_no_election_type_falls_back_to_metadata(mock_election):
    mock_election.election_type = ""
    mock_election.source_metadata = {"az_election_name": "2026 Primary Election"}
    mock_election.save()
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML) as mock_fetch:
        adapter.fetch_results(mock_election.election_date, mock_election.pk)
    called_url = mock_fetch.call_args[0][0]
    assert "2026%20Primary%20Election" in called_url


@pytest.mark.django_db
def test_fetch_results_error_raises(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", side_effect=OSError("connection error")):
        with pytest.raises(OSError):
            adapter.fetch_results(mock_election.election_date, mock_election.pk)


@pytest.mark.django_db
def test_fetch_results_source_url_is_https(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert result.source_url.startswith("https://apps.azsos.gov")
