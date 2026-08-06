"""Tests for the Hawaii results adapter."""

from __future__ import annotations

import hashlib
import textwrap
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election, Race
from results.models import OfficialResult

pytestmark = pytest.mark.django_db


SUMMARY_TEXT = "\n".join([
    "Format#1",
    "#Contest ID,Contest Title,Contest Seq Nbr,Contest Type,Contest Party,Mail Blank Votes,In-Person Blank Votes,Mail Over Votes,In-Person Over Votes,Mail Invalid Votes,In-Person Invalid Votes,Registered Voters,Total Precincts,Counted Precincts,Candidate ID,Candidate Name,Candidate Seq Nbr,Candidate Party,Mail Votes,In-Person Votes,Total Votes",
    '"283","President and Vice President","1","OF",,"4882","128","498","27","0","0","860868","497","497","1","(D) HARRIS, Kamala D. \r\nFor PRESIDENT\r\nWALZ, Tim \r\nFor VICE PRESIDENT","2",,"300312","12732","313044",',
    '"283","President and Vice President","1","OF",,"4882","128","498","27","0","0","860868","497","497","2","(R) TRUMP, Donald J. \r\nFor PRESIDENT\r\nVANCE, JD \r\nFor VICE PRESIDENT","6",,"168016","25645","193661",',
    '"297","Question #1","64","MS",,"38098","2793","2010","155","0","0","860868","494","494","2","YES","1",,"253321","14717","268038",',
    '"297","Question #1","64","MS",,"38098","2793","2010","155","0","0","860868","494","494","1","NO","2",,"189649","21493","211142",',
]).encode("utf-16")


MEDIA_TEXT = "\n".join([
    "Format#1",
    '#"Precinct_Name","Split_Name","precinct_splitId","Reg_voters","Ballots","Reporting","Contest_id","Contest_title","Contest_party","Choice_id","Candidate_name","Choice_party","Candidate_Type","Mail votes","In-Person votes"',
    '"01-01",,"1","6628","4074","1","283","President and Vice President",,"1","(D) HARRIS, Kamala D. \r\nFor PRESIDENT\r\nWALZ, Tim \r\nFor VICE PRESIDENT",,"C","2748","0",',
    '"01-01",,"1","6628","4074","1","283","President and Vice President",,"2","(R) TRUMP, Donald J. \r\nFor PRESIDENT\r\nVANCE, JD \r\nFor VICE PRESIDENT",,"C","1160","0",',
]).encode("utf-16")


INDEX_HTML = """
<html>
  <body>
    <a href="https://files.hawaii.gov/elections/files/results/2024/General/summary.txt">Statewide Summary</a>
    <a href="https://files.hawaii.gov/elections/files/results/2024/General/media.txt">Statewide Precinct Detail</a>
  </body>
</html>
"""


def _mock_response(*, content: bytes = b"", text: str = "", status_code: int = 200):
    resp = MagicMock()
    resp.content = content
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    return resp


def test_parse_summary_text_extracts_rows_and_normalizes_party_prefix():
    from results.adapters.hi import _parse_summary_text

    rows = _parse_summary_text(SUMMARY_TEXT, source_url="https://elections.hawaii.gov/election-results/")

    assert len(rows) == 4

    dem = next(row for row in rows if row.candidate_name == "HARRIS, Kamala D.")
    rep = next(row for row in rows if row.candidate_name == "TRUMP, Donald J.")
    yes = next(row for row in rows if row.candidate_name == "YES")

    assert dem.vote_count == 313044
    assert dem.is_winner is True
    assert dem.raw["party_code"] == "D"
    assert dem.raw["contest_variant"] == "hi:president and vice president:democratic"
    assert rep.vote_count == 193661
    assert rep.is_winner is True
    assert yes.option_label is None
    assert yes.office_title == "Question #1"
    assert yes.raw["contest_type"] == "MS"


def test_parse_media_text_extracts_precinct_rows():
    from results.adapters.hi import _parse_media_text

    rows = _parse_media_text(MEDIA_TEXT, source_url="https://elections.hawaii.gov/election-results/")

    assert len(rows) == 2
    assert rows[0].jurisdiction_fragment == "1"
    assert rows[0].vote_count == 2748
    assert rows[0].raw["precinct_name"] == "01-01"
    assert rows[0].raw["contest_variant"] == "hi:president and vice president:democratic"


@patch("results.adapters.hi.requests.get")
@patch("results.adapters.hi.cache")
def test_fetch_results_discovers_files_from_index_and_matches_contest_variant(mock_cache, mock_get):
    from results.adapters.hi import HawaiiAdapter

    election = Election.objects.create(
        name="2024 Hawaii General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="HI",
        source_id="hi_2024_general",
        status=Election.Status.RESULTS_PENDING,
    )
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="President and Vice President",
        jurisdiction="Hawaii",
        geography_scope="statewide",
        source=Race.Source.HI_OLVR,
        certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source_metadata={"contest_variant": "hi:president and vice president:democratic"},
    )

    mock_cache.get.return_value = None

    def side_effect(url, timeout=60, **kwargs):
        if url == "https://elections.hawaii.gov/election-results/":
            return _mock_response(text=INDEX_HTML)
        if url.endswith("/summary.txt"):
            return _mock_response(content=SUMMARY_TEXT)
        if url.endswith("/media.txt"):
            return _mock_response(content=MEDIA_TEXT)
        raise AssertionError(f"unexpected url {url}")

    mock_get.side_effect = side_effect

    result = HawaiiAdapter().fetch_results(election.election_date, election.pk)

    expected_version = "|".join(
        [
            hashlib.sha256(SUMMARY_TEXT).hexdigest(),
            hashlib.sha256(MEDIA_TEXT).hexdigest(),
        ]
    )

    assert result.source_url == "https://elections.hawaii.gov/election-results/"
    assert result.mapping_confidence == "full"
    assert result.source_version == expected_version
    assert any(row.raw.get("contest_variant") == "hi:president and vice president:democratic" for row in result.rows)
    assert any(row.jurisdiction_fragment == "1" for row in result.rows)


@patch("results.adapters.hi.requests.get")
@patch("results.adapters.hi.cache")
def test_fetch_results_returns_unchanged_when_fingerprint_is_cached(mock_cache, mock_get):
    from results.adapters.hi import HawaiiAdapter

    election = Election.objects.create(
        name="2024 Hawaii General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="HI",
        source_id="hi_2024_general_cached",
        status=Election.Status.RESULTS_PENDING,
    )

    fingerprint = "|".join(
        [
            hashlib.sha256(SUMMARY_TEXT).hexdigest(),
            hashlib.sha256(MEDIA_TEXT).hexdigest(),
        ]
    )
    mock_cache.get.return_value = fingerprint

    def side_effect(url, timeout=60, **kwargs):
        if url == "https://elections.hawaii.gov/election-results/":
            return _mock_response(text=INDEX_HTML)
        if url.endswith("/summary.txt"):
            return _mock_response(content=SUMMARY_TEXT)
        if url.endswith("/media.txt"):
            return _mock_response(content=MEDIA_TEXT)
        raise AssertionError(f"unexpected url {url}")

    mock_get.side_effect = side_effect

    result = HawaiiAdapter().fetch_results(election.election_date, election.pk)

    assert result.unchanged is True
    assert result.rows == []
    assert result.source_version == fingerprint
