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
