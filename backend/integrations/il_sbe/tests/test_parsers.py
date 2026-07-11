import os

import pytest

from integrations.il_sbe.parsers import (
    parse_category_offices,
    parse_election_id_token,
    parse_election_options,
    parse_postback_fields,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_postback_fields_extracts_viewstate_trio():
    html = _load_fixture("search_page.html")
    fields = parse_postback_fields(html)
    assert set(fields.keys()) == {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"}
    assert len(fields["__VIEWSTATE"]) > 1000
    assert fields["__VIEWSTATEGENERATOR"]
    assert fields["__EVENTVALIDATION"]


def test_parse_election_options_returns_value_label_pairs():
    html = _load_fixture("search_page.html")
    options = parse_election_options(html)
    assert len(options) > 40
    assert {"value": "69", "label": "2026 GENERAL PRIMARY"} in options
    assert {"value": "66", "label": "2024 GENERAL ELECTION"} in options


def test_parse_election_id_token_decodes_from_federal_statewide_link():
    html = _load_fixture("search_page.html")
    token = parse_election_id_token(html)
    assert token == "Z2J/vYpKX8w="


def test_parse_election_id_token_returns_none_when_link_missing():
    assert parse_election_id_token("<html><body>no links here</body></html>") is None


def test_parse_category_offices_extracts_office_name_and_csv_url():
    html = _load_fixture("category_federal_statewide.html")
    offices = parse_category_offices(html)
    assert len(offices) > 20

    senate = next(o for o in offices if o["office_name"] == "UNITED STATES SENATOR")
    assert senate["csv_url"] == (
        "https://www.elections.il.gov/Downloads/ElectionOperations/ElectionResults/"
        "ByOffice/69/69-150-UNITED STATES SENATOR-2026GP.csv"
    )

    governor = next(o for o in offices if o["office_name"] == "GOVERNOR AND LIEUTENANT GOVERNOR")
    assert "69-180-GOVERNOR AND LIEUTENANT GOVERNOR-2026GP.csv" in governor["csv_url"]
