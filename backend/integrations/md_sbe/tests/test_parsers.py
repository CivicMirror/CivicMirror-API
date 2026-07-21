import os

from integrations.md_sbe.parsers import parse_county_results_csv

FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "results", "tests", "fixtures"
)


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_county_results_csv_extracts_all_candidate_rows():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    assert len(rows) == 9
    by_name = {r["candidate_name"]: r for r in rows}
    assert "Angela Alsobrooks" in by_name
    assert "Other Write-Ins" in by_name


def test_parse_county_results_csv_extracts_expected_fields():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    alsobrooks = next(r for r in rows if r["candidate_name"] == "Angela Alsobrooks")

    assert alsobrooks["office_name"] == "U.S. Senator"
    assert alsobrooks["party"] == "DEM"
    assert alsobrooks["is_winner"] is True
    assert alsobrooks["is_write_in"] is False
    assert alsobrooks["total_votes"] == 7396


def test_parse_county_results_csv_distinguishes_winner_from_write_in_column():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    burke = next(r for r in rows if r["candidate_name"] == "Patrick J. Burke")

    # Burke is a write-in, not the contest winner — Winner and Write-In? are
    # different columns and must not be conflated.
    assert burke["is_winner"] is False
    assert burke["is_write_in"] is True
    assert burke["total_votes"] == 17


def test_parse_county_results_csv_handles_comma_thousands_and_blank_against_columns():
    csv_text = (
        '"Office Name","Office District","Candidate Name","Party","Winner","Write-In?",'
        '"Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against",'
        '"Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes",'
        '"Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against",'
        '"Total Votes","Total Votes Against"\n'
        '"President - Vice Pres","","Kamala D. Harris and Tim Walz","DEM","Y","","1,752","",'
        '"4,032","","2,740","","641","","66","","9,231",""\n'
    )
    rows = parse_county_results_csv(csv_text)
    assert rows[0]["total_votes"] == 9231


def test_parse_county_results_csv_skips_rows_with_no_office_name():
    csv_text = (
        '"Office Name","Candidate Name","Party","Winner","Write-In?","Total Votes"\n'
        '"","","","","",""\n'
    )
    assert parse_county_results_csv(csv_text) == []
