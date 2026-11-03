from pathlib import Path

from integrations.mi_sos.parsers import (
    parse_boe_candidate_listing,
    parse_mvic_county_results_html,
    parse_mvic_elections,
    parse_mvic_result_file,
    parse_mvic_result_status,
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


# ---------------------------------------------------------------------------
# MVIC bulk result file: preamble, header, trailer, and per-county rows
# ---------------------------------------------------------------------------

def _result_file() -> str:
    return _fixture("mvic_result_file_706.txt")


def test_parse_mvic_result_file_skips_the_preamble_and_trailer():
    """Real MVIC output, captured from electionId=706.

    Line 1 is "TOTAL VOTER TURNOUT: ...", line 2 the header, and the last line
    "RECORDS: n  RESULTS: OFFICIAL". Handing the whole file to csv.DictReader takes
    the preamble as the header and yields nothing usable.
    """
    rows = parse_mvic_result_file(_result_file())

    assert rows
    assert not [r for r in rows if "TOTAL VOTER TURNOUT" in r["contest"]]
    assert not [r for r in rows if r["contest"].startswith("RECORDS:")]


def test_parse_mvic_result_file_reads_the_real_column_names():
    """Office, name and votes live in OfficeDescription/CandidateLastName/CandidateVotes."""
    rows = parse_mvic_result_file(_result_file())
    alcona = [
        r for r in rows
        if r["county"] == "ALCONA" and r["contest"].startswith("GOVERNOR 4 YEAR")
    ]

    benson = next(r for r in alcona if r["candidate_name"] == "Benson, Jocelyn")
    assert benson["party"] == "DEMOCRATIC"
    assert benson["votes"] == "1054"
    # The file carries no percentages.
    assert benson["vote_pct"] == ""


def test_candidate_names_are_assembled_as_last_comma_given():
    """The BOE candidate listing uses the same shape, which is how the two match up."""
    names = {r["candidate_name"] for r in parse_mvic_result_file(_result_file())}

    assert "Benson, Jocelyn" in names
    assert "Swanson, Christopher Robert" in names


def test_county_rows_are_summed_into_contest_totals():
    """results.winners only derives winners from contest-total rows.

    It refuses to sum sub-jurisdiction rows itself because fragments can overlap;
    Michigan's counties partition the state, so the parser sums them.
    """
    rows = parse_mvic_result_file(_result_file())
    totals = [r for r in rows if r["county"] == ""]
    counties = [r for r in rows if r["county"]]

    assert totals and counties
    governor = [r for r in totals if r["contest"].startswith("GOVERNOR 4 YEAR")]
    benson = next(r for r in governor if r["candidate_name"] == "Benson, Jocelyn")
    expected = sum(
        int(r["votes"]) for r in counties
        if r["candidate_name"] == "Benson, Jocelyn" and r["contest"].startswith("GOVERNOR 4 YEAR")
    )
    assert int(benson["votes"]) == expected
    assert benson["raw"]["aggregated_from"] == "county"


def test_write_in_rows_are_flagged():
    rows = parse_mvic_result_file(_result_file())

    write_ins = [r for r in rows if r["write_in"]]
    assert write_ins
    assert all("WRITE-IN" in r["candidate_name"].upper() or r["party"].upper() == "WRITE-IN"
               for r in write_ins)


def test_result_status_comes_from_the_files_own_trailer():
    """MVIC states this explicitly, so a race is not certified from election-night data."""
    assert parse_mvic_result_status(_result_file()) == "official"
    assert parse_mvic_result_status(
        "TOTAL VOTER TURNOUT: 1\r\nElectionDate\tOfficeDescription\r\nRECORDS: 0\tRESULTS: UNOFFICIAL\r\n"
    ) == "unofficial"
    # Unknown or missing is treated as unofficial rather than assumed final.
    assert parse_mvic_result_status("no trailer here") == "unofficial"


def test_parse_mvic_result_file_without_a_header_returns_nothing():
    assert parse_mvic_result_file("TOTAL VOTER TURNOUT: 5\r\nnothing useful\r\n") == []
    assert parse_mvic_result_file("") == []


# ---------------------------------------------------------------------------
# MVIC county vote records: a Bootstrap grid, not lines of text
# ---------------------------------------------------------------------------

def _county() -> list[dict[str, str]]:
    return parse_mvic_county_results_html(_fixture("mvic_county_records_706.html"))


def test_parse_mvic_county_results_html_returns_candidate_rows():
    """Real MVIC output, captured from electionId=706 (Aug 4, 2026 primary).

    The previous implementation flattened the page and required name, votes and
    percent on one line separated by two or more spaces. That is how the old
    hand-written fixture was shaped and not how MVIC renders anything: the real
    document yielded zero rows.
    """
    rows = _county()
    assert rows

    benson = next(r for r in rows if r["candidate_name"] == "Benson, Jocelyn")
    assert benson["contest"] == "GOVERNOR 4 YEAR TERM (1) POSITION"
    assert benson["party"] == "DEMOCRATIC"
    assert benson["votes"] == "1251160"
    assert benson["vote_pct"] == "83.22"
    # This endpoint reports statewide contest totals, so results.tasks keys them
    # on an empty jurisdiction_fragment.
    assert benson["county"] == ""


def test_party_and_contest_subtotal_rows_are_not_read_as_candidates():
    """"Party Votes:" rows share a result row's shape and differ only by a class."""
    rows = _county()

    assert not [r for r in rows if "Votes:" in r["candidate_name"]]
    assert all(r["votes"] for r in rows)


def test_each_candidate_row_carries_its_own_party():
    """MVIC repeats the party per row rather than using party header rows."""
    governor = [r for r in _county() if r["contest"].startswith("GOVERNOR 4 YEAR")]

    assert {r["party"] for r in governor} == {"DEMOCRATIC", "REPUBLICAN"}
    james = next(r for r in governor if r["candidate_name"] == "James, John")
    assert james["party"] == "REPUBLICAN"
    assert james["vote_pct"] == "50.05"


def test_contest_titles_normalize_to_the_races_the_candidate_listing_creates():
    from integrations.mi_sos.mappers import result_office_title

    titles = {result_office_title(r["contest"]) for r in _county()}

    assert "Governor" in titles
    assert "U.S. Senate" in titles
    assert "U.S. House - District 1" in titles
    assert "State Senate - District 35" in titles


def test_county_results_without_the_results_pane_yield_nothing():
    assert parse_mvic_county_results_html("<html><body><div class='row'>x</div></body></html>") == []
    assert parse_mvic_county_results_html("") == []


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
