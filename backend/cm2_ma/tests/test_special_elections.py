from datetime import date
from pathlib import Path

from cm2_ma.constants import SPECIAL_ELECTIONS_INDEX_URL
from cm2_ma.sources.special_elections import (
    MaSpecialElectionCalendarSource,
    MaSpecialElectionsIndexSource,
    parse_special_election_calendar,
    parse_special_elections_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_index_parser_returns_unique_absolute_calendar_urls_in_order():
    urls = parse_special_elections_index(
        (FIXTURES / "special_elections_index.html").read_bytes()
    )

    assert urls == (
        "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election6.htm",
        "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election7.htm",
    )


def test_index_parser_excludes_past_special_election_links():
    urls = parse_special_elections_index(
        (FIXTURES / "special_elections_index.html").read_bytes()
    )

    assert not any("past-special-elections" in url for url in urls)


def test_index_source_url_is_configured():
    assert MaSpecialElectionsIndexSource().url == SPECIAL_ELECTIONS_INDEX_URL


def test_calendar_parser_extracts_only_the_primary_and_general_rows():
    records = parse_special_election_calendar(
        (FIXTURES / "special_election_calendar.html").read_bytes(),
        source_artifact_public_id="artifact/ma-special-5th-essex",
    )

    assert [(record.election_date, record.election_type) for record in records] == [
        (date(2026, 3, 3), "special_primary"),
        (date(2026, 3, 31), "special_general"),
    ]
    assert all("5th Essex Representative District" in record.name for record in records)
    assert all(
        "death of Representative Ann-Margaret Ferrante" in record.name for record in records
    )
    assert {record.source_artifact_public_id for record in records} == {
        "artifact/ma-special-5th-essex"
    }


def test_calendar_parser_ignores_non_matching_deadline_rows():
    records = parse_special_election_calendar(
        (FIXTURES / "special_election_calendar.html").read_bytes()
    )

    assert len(records) == 2


def test_calendar_source_uses_constructor_provided_url():
    url = "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election7.htm"
    source = MaSpecialElectionCalendarSource(url=url)

    assert source.url == url

    records = source.parse((FIXTURES / "special_election_calendar.html").read_bytes())
    assert len(records) == 2
