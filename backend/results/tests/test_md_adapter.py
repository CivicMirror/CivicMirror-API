import os

from integrations.md_sbe.parsers import parse_county_results_csv
from results.adapters.md_aggregate import aggregate_county_rows

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _county_rows():
    county01 = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    county02 = parse_county_results_csv(_load_fixture("md_county02_us_senator.csv"))
    return county01 + county02


def test_aggregate_county_rows_sums_total_votes_across_counties():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))

    by_name = {r.candidate_name: r.vote_count for r in rows}
    # 7396 (county 01) + 137645 (county 02) = 145041
    assert by_name["Angela Alsobrooks"] == 145041
    # 21811 + 164698 = 186509
    assert by_name["Larry Hogan"] == 186509


def test_aggregate_county_rows_marks_winner_true_if_any_county_row_says_so():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    alsobrooks = next(r for r in rows if r.candidate_name == "Angela Alsobrooks")
    hogan = next(r for r in rows if r.candidate_name == "Larry Hogan")

    assert alsobrooks.is_winner is True
    assert hogan.is_winner is False


def test_aggregate_county_rows_flags_write_in_aggregate():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    write_ins = next(r for r in rows if r.candidate_name == "Other Write-Ins")

    assert write_ins.is_write_in_aggregate is True
    # 86 (county 01) + 621 (county 02) = 707
    assert write_ins.vote_count == 707


def test_aggregate_county_rows_sets_office_title_and_result_type():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    for row in rows:
        assert row.office_title == "U.S. Senator"
        assert row.result_type == "official"


def test_aggregate_county_rows_excludes_offices_not_in_allowlist():
    county_rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    # Allowlist a different office than what's in the fixture.
    rows = aggregate_county_rows(county_rows, office_allowlist=frozenset({"Governor"}))
    assert rows == []
