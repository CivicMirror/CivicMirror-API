from pathlib import Path

from integrations.mi_sos.parsers import (
    parse_boe_candidate_listing,
    parse_mvic_county_results_html,
    parse_mvic_elections,
    parse_mvic_result_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_mvic_elections_extracts_ids_dates_and_types():
    elections = parse_mvic_elections(_fixture("mvic_votehistory.html"))
    by_id = {e["election_id"]: e for e in elections}

    assert "705" in by_id
    assert by_id["705"]["date"] == "5/5/2026"
    assert "MAY CONSOLIDATED" in by_id["705"]["name"].upper()


def test_parse_mvic_elections_returns_empty_for_missing_select():
    assert parse_mvic_elections("<html><body>No elections</body></html>") == []


def test_parse_boe_candidate_listing_extracts_contests_and_candidates():
    rows = parse_boe_candidate_listing(_fixture("boe_candidate_listing_2026_primary.html"))

    assert len(rows) == 3
    assert rows[0] == {
        "office_title": "GOVERNOR 4 Year Term (1) Position",
        "party": "Democratic",
        "incumbent": "",
        "filing_method": "Petitions",
        "status": "",
        "candidate_name": "Jane Candidate",
        "candidate_address": "1 Main St Lansing MI",
        "filed_on": "4/21/2026",
    }


def test_parse_boe_candidate_listing_preserves_withdrawn_and_disqualified_statuses():
    rows = parse_boe_candidate_listing(_fixture("boe_candidate_listing_2026_primary.html"))
    statuses = {row["status"] for row in rows}
    assert {"DISQ", "WITHD"} <= statuses


def test_parse_mvic_result_file_returns_candidate_rows():
    rows = parse_mvic_result_file(_fixture("mvic_result_file_705.tsv"))
    assert len(rows) == 3
    assert rows[0]["contest"] == "35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027"
    assert rows[0]["candidate_name"] == "GREENE, CHEDRICK"
    assert rows[0]["votes"] == "36583"
    assert rows[0]["vote_pct"] == "58.88"
    assert rows[0]["county"] == "BAY"


def test_parse_mvic_county_results_html_returns_candidate_rows():
    rows = parse_mvic_county_results_html(_fixture("mvic_county_records_705.html"))
    assert len(rows) == 3
    names = {row["candidate_name"] for row in rows}
    assert "GREENE, CHEDRICK" in names
    greene = next(row for row in rows if row["candidate_name"] == "GREENE, CHEDRICK")
    assert greene["votes"] == "36583"
    assert greene["vote_pct"] == "58.88"


# ---------------------------------------------------------------------------
# The real general-election listing: nested tables and a different column order
# ---------------------------------------------------------------------------

def _general() -> list[dict[str, str]]:
    return parse_boe_candidate_listing(_fixture("boe_candidate_listing_2026_general.html"))


def test_general_listing_yields_the_partisan_slate_not_only_judicial_offices():
    """The Nov 3, 2026 regression: only non-partisan offices were being parsed.

    Hardcoded column indices read the combined "Party / Incumbent" column as the
    status column, so every row with a party in it failed the status check. Judicial
    offices have no party, so they passed and nothing else did.
    """
    rows = _general()
    offices = {r["office_title"] for r in rows}

    assert any(o.startswith("Governor / Lt. Governor") for o in offices)
    assert any(o.startswith("U.S. Senate") for o in offices)
    assert any(o.startswith("Secretary of State") for o in offices)
    assert any("Representative in Congress" in o for o in offices)
    assert any("State Senator" in o for o in offices)
    assert any("Representative in State Legislature" in o for o in offices)
    # ... and the judicial offices that used to be the only survivors.
    assert any("Justice of Supreme Court" in o for o in offices)


def test_general_listing_reads_party_name_and_dates_from_the_right_columns():
    governor = [r for r in _general() if r["office_title"].startswith("Governor / Lt. Governor")]

    by_party = {r["party"]: r for r in governor}
    assert "Democratic Party" in by_party
    assert "Republican Party" in by_party
    assert by_party["Democratic Party"]["candidate_name"] == "Benson, Jocelyn / Brinks, Winnie"
    assert by_party["Democratic Party"]["filed_on"] == "04/16/2026"
    assert by_party["Democratic Party"]["filing_method"] == "Petitions"
    # Every one of these is a live candidacy, so the status column must be empty.
    assert {r["status"] for r in governor} == {""}


def test_general_listing_squashes_the_non_breaking_space_in_running_mates():
    names = [r["candidate_name"] for r in _general() if " / " in r["candidate_name"]]

    assert names, "expected at least one running-mate ticket"
    for name in names:
        assert "\xa0" not in name
        assert "  " not in name


def test_general_listing_separates_the_incumbent_marker_from_the_party():
    """One source column holds either a party or the literal "INCUMBENT"."""
    incumbents = [r for r in _general() if r["incumbent"]]

    assert incumbents
    for row in incumbents:
        assert row["incumbent"].upper() == "INCUMBENT"
        assert row["party"] == ""


def test_general_listing_keeps_disqualified_and_withdrawn_filings():
    assert any(r["status"] == "DISQ" for r in _general())


def test_nested_report_table_does_not_swallow_every_cell():
    """The live document wraps the report in a one-cell layout table.

    A recursive cell search on the outer row returns every cell in the document, so
    the first row looked like a ~10,000-cell row and no office header was ever found.
    """
    html = _fixture("boe_candidate_listing_2026_general.html")
    assert html.count("<table") > 1, "fixture must keep the nesting it is testing"
    assert _general(), "nested wrapper must not prevent parsing"
