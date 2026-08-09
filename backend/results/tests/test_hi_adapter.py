"""Tests for the Hawaii results adapter."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election, Race
from results.models import OfficialResult

pytestmark = pytest.mark.django_db


# Fixtures are verbatim rows from the real Office of Elections files. Hawaii
# publishes two different shapes and the adapter has to handle both:
#
#   general_summary.txt - Contest Party column empty, party carried as a "(D) "
#                         prefix on the candidate name
#   primary_summary.txt - Contest Party column populated (D/R/G/L/N/W/NON),
#                         candidate names bare
#
# The previous hand-written fixture used the general shape while asserting
# primary-style expectations, which is why every test passed against an adapter
# that produced empty parties on real primary files.
_FIXTURES = Path(__file__).parent / "fixtures" / "hi"
SUMMARY_TEXT = (_FIXTURES / "general_summary.txt").read_bytes()
PRIMARY_SUMMARY_TEXT = (_FIXTURES / "primary_summary.txt").read_bytes()
MEDIA_TEXT = (_FIXTURES / "primary_media.txt").read_bytes()
PLACEHOLDER_TEXT = (_FIXTURES / "placeholder_summary.txt").read_bytes()


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


def test_parse_summary_text_reads_party_from_general_name_prefix():
    from results.adapters.hi import _parse_summary_text

    rows = _parse_summary_text(SUMMARY_TEXT, source_url="https://elections.hawaii.gov/election-results/")

    dem = next(row for row in rows if row.candidate_name == "HARRIS, Kamala D.")
    rep = next(row for row in rows if row.candidate_name == "TRUMP, Donald J.")
    yes = next(row for row in rows if row.candidate_name == "YES")

    assert dem.vote_count == 313044
    assert dem.raw["party_code"] == "D"
    assert dem.raw["contest_variant"] == "hi:president and vice president:democratic"
    assert rep.raw["contest_variant"] == "hi:president and vice president:republican"
    assert yes.option_label is None
    assert yes.raw["contest_type"] == "MS"


def test_parse_summary_text_reads_party_from_primary_contest_column():
    """Primary files leave candidate names bare and put the party in column 4."""
    from results.adapters.hi import _parse_summary_text

    rows = _parse_summary_text(PRIMARY_SUMMARY_TEXT, source_url="https://elections.hawaii.gov/")

    assert rows, "fixture should contain rows"
    # Every row must resolve a party. Reading only the name prefix left all of
    # them empty, which broke the join to Stage 1 races entirely.
    assert all(row.raw["party_name"] for row in rows)

    senator = [r for r in rows if r.raw["contest_title"] == "U.S. Senator"]
    assert {r.raw["party_name"] for r in senator} == {"GREEN", "REPUBLICAN"}

    # "NON" is how the primary files spell the candidate report's
    # "NONPARTISAN SPECIAL" (county and OHA contests).
    mayor = next(r for r in rows if r.raw["contest_title"] == "Mayor")
    assert mayor.raw["party_name"] == "NONPARTISAN SPECIAL"
    assert mayor.raw["contest_variant"] == "hi:mayor:nonpartisan special"


def test_parse_summary_text_marks_one_winner_per_contest():
    """A general contest has a single winner, not one winner per party."""
    from results.adapters.hi import _parse_summary_text

    rows = _parse_summary_text(SUMMARY_TEXT, source_url="https://elections.hawaii.gov/")

    president = [r for r in rows if r.raw["contest_id"] == "283"]
    winners = [r for r in president if r.is_winner]

    assert len(president) > 1
    assert [w.candidate_name for w in winners] == ["HARRIS, Kamala D."]


def test_parse_summary_text_keeps_same_titled_contests_distinct():
    """'Mayor' covers two counties in 2024; contest_id keeps them apart."""
    from results.adapters.hi import _parse_summary_text

    rows = _parse_summary_text(PRIMARY_SUMMARY_TEXT, source_url="https://elections.hawaii.gov/")

    mayor_ids = {r.raw["contest_id"] for r in rows if r.raw["contest_title"] == "Mayor"}
    assert len(mayor_ids) == 2

    # Winners are scoped per contest id, so each county gets exactly one.
    for contest_id in mayor_ids:
        group = [r for r in rows if r.raw["contest_id"] == contest_id]
        assert sum(1 for r in group if r.is_winner) == 1


def test_parse_media_text_extracts_precinct_rows():
    from results.adapters.hi import _parse_media_text

    rows = _parse_media_text(MEDIA_TEXT, source_url="https://elections.hawaii.gov/election-results/")

    assert rows
    assert all(row.jurisdiction_fragment for row in rows)
    assert all(row.raw["file_kind"] == "media" for row in rows)
    assert all(row.raw["party_name"] for row in rows)


def test_discover_result_urls_does_not_fall_back_to_another_year():
    """A 2026 election must never resolve to the 2024 files sitting on the index."""
    from results.adapters.hi import _discover_result_urls

    election = Election(
        election_date=date(2026, 8, 8), election_type="primary", state="HI",
    )
    index_html = (
        '<a href="https://files.hawaii.gov/elections/files/results/2024/General/summary.txt">2024</a>'
        '<a href="https://files.hawaii.gov/elections/files/results/2024/General/media.txt">2024</a>'
    )

    assert _discover_result_urls(index_html, election) == ("", "")


def test_discover_result_urls_matches_year_and_section():
    from results.adapters.hi import _discover_result_urls

    election = Election(
        election_date=date(2024, 11, 5), election_type="general", state="HI",
    )
    index_html = (
        '<a href="https://files.hawaii.gov/elections/files/results/2024/Primary/summary.txt">p</a>'
        '<a href="https://files.hawaii.gov/elections/files/results/2024/General/summary.txt">g</a>'
        '<a href="https://files.hawaii.gov/elections/files/results/2024/General/media.txt">g</a>'
    )

    summary_url, media_url = _discover_result_urls(index_html, election)

    assert summary_url.endswith("/2024/General/summary.txt")
    assert media_url.endswith("/2024/General/media.txt")


def test_discover_result_urls_matches_single_segment_year_section():
    """2026 moved from /{year}/{section}/ to a single "{year} {section}" segment."""
    from results.adapters.hi import _discover_result_urls

    election = Election(
        election_date=date(2026, 8, 8), election_type="primary", state="HI",
    )
    index_html = (
        '<a href="https://elections.hawaii.gov/wp-content/results/2026 Primary/summary.txt">2026</a>'
        '<a href="https://elections.hawaii.gov/wp-content/results/2026 Primary/media.txt">2026</a>'
        '<a href="https://files.hawaii.gov/elections/files/results/2024/Primary/summary.txt">2024</a>'
    )

    summary_url, media_url = _discover_result_urls(index_html, election)

    assert summary_url.endswith("2026 Primary/summary.txt")
    assert media_url.endswith("2026 Primary/media.txt")


def test_decode_result_text_handles_non_utf16_placeholder():
    """The pre-election stub is plain ASCII; utf-16 decoding raised on it."""
    from results.adapters.hi import _decode_result_text, _looks_like_result_file

    text = _decode_result_text(PLACEHOLDER_TEXT)

    assert "later date" in text
    assert _looks_like_result_file(text) is False
    assert _looks_like_result_file(_decode_result_text(SUMMARY_TEXT)) is True


def test_decode_result_text_prefers_utf8_over_blind_utf16_guess():
    """No-BOM ASCII bytes must not be misread as UTF-16 mojibake.

    2026's files ship as plain UTF-8 with no BOM, unlike every prior year's
    UTF-16+BOM export. A bare "try utf-16 first" guess rarely raises
    UnicodeDecodeError on ASCII-ish bytes -- it just silently produces
    garbage instead of falling through to utf-8.
    """
    from results.adapters.hi import _decode_result_text, _looks_like_result_file

    no_bom_utf8 = (
        "#FormatVersion 1\r\n"
        "#Contest ID\tContest Title\tContest Type\r\n"
        "338\tU.S. Representative, Dist I\tOF\r\n"
    ).encode("utf-8")

    text = _decode_result_text(no_bom_utf8)

    assert text.startswith("#FormatVersion 1")
    assert _looks_like_result_file(text) is True


def test_parse_summary_text_handles_tab_delimited_2026_shape():
    """2026 switched from comma-delimited "Format#1" files to tab-delimited
    "#FormatVersion 1" files. The parser must detect the delimiter instead
    of hardcoding comma, or every row is dropped as short/malformed.
    """
    from results.adapters.hi import _parse_summary_text

    tab_delimited = (
        "#FormatVersion 1\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\r\n"
        "#Contest ID\tContest Title\tContest Seq Nbr\tContest Type\tContest Party\t"
        "Mail Blank Votes\tIn-Person Blank Votes\tMail Over Votes\tIn-Person Over Votes\t"
        "Mail Invalid Votes\tIn-Person Invalid Votes\tRegistered Voters\tTotal Precincts\t"
        "Counted Precincts\tCandidate ID\tCandidate Name\tCandidate Seq Nbr\t"
        "Candidate Party\tMail Votes\tIn-Person Votes\tTotal Votes\r\n"
        '338\t"U.S. Representative, Dist I"\t1\tOF\tN\t696\t17\t0\t0\t1912\t38\t846543\t223\t1\t'
        '1\t"BERNING, Nathan M."\t1\t\t856\t21\t877\r\n'
    ).encode("utf-8")

    rows = _parse_summary_text(tab_delimited, source_url="https://elections.hawaii.gov/")

    assert len(rows) == 1
    assert rows[0].candidate_name == "BERNING, Nathan M."
    assert rows[0].vote_count == 877


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
