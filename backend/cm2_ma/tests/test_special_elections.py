from pathlib import Path

from cm2_ma.constants import SPECIAL_ELECTIONS_INDEX_URL
from cm2_ma.sources.special_elections import (
    MaSpecialElectionsIndexSource,
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
