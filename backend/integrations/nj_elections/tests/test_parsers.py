import os

import pytest

from integrations.nj_elections.parsers import classify_clarity_counties, parse_county_urls

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_county_urls_extracts_all_21_counties():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    assert len(counties) == 21
    names = {c["county"] for c in counties}
    assert "Atlantic" in names
    assert "Cape May" in names  # multi-word county name
    assert "Bergen" in names  # non-Clarity county still gets parsed here


def test_parse_county_urls_captures_real_clarity_url():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    atlantic = next(c for c in counties if c["county"] == "Atlantic")
    assert atlantic["url"] == "https://results.enr.clarityelections.com/NJ/Atlantic/126380/web.345435/#/summary"


def test_classify_clarity_counties_returns_16_in_scope():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    assert len(clarity) == 16
    names = {c["county"] for c in clarity}
    assert names == {
        "Atlantic", "Burlington", "Cape May", "Cumberland", "Essex", "Gloucester",
        "Hudson", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic",
        "Salem", "Somerset", "Union",
    }


def test_classify_clarity_counties_excludes_off_platform_counties():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    names = {c["county"] for c in clarity}
    for excluded in ("Bergen", "Camden", "Sussex", "Warren", "Hunterdon"):
        assert excluded not in names


def test_classify_clarity_counties_extracts_election_id_when_present():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    atlantic = next(c for c in clarity if c["county"] == "Atlantic")
    assert atlantic["election_id"] == "126380"


def test_classify_clarity_counties_returns_none_id_when_not_posted():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    for county_name in ("Cumberland", "Passaic", "Somerset"):
        entry = next(c for c in clarity if c["county"] == county_name)
        assert entry["election_id"] is None
