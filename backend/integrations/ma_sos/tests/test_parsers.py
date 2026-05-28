"""
Tests for integrations.ma_sos.parsers — HTML and CSV parsing functions.
All tests are pure unit tests (no DB, no HTTP).
"""
import textwrap

import pytest

from integrations.ma_sos import parsers

# ---------------------------------------------------------------------------
# parse_election_search_html
# ---------------------------------------------------------------------------

ELECTION_SEARCH_HTML = """
<html><body>
<table id="search_results_table">
  <tr id="election-id-165300">
    <td>2024</td>
    <td>President</td>
    <td>Statewide</td>
    <td>General</td>
  </tr>
  <tr id="election-id-165304">
    <td>2024</td>
    <td>U.S. Senate</td>
    <td></td>
    <td>General</td>
  </tr>
  <tr id="not-an-election">
    <td>ignored</td>
  </tr>
</table>
</body></html>
"""


def test_parse_election_search_html_returns_rows():
    rows = parsers.parse_election_search_html(ELECTION_SEARCH_HTML)
    assert len(rows) == 2


def test_parse_election_search_html_ids():
    rows = parsers.parse_election_search_html(ELECTION_SEARCH_HTML)
    ids = {r["election_id"] for r in rows}
    assert ids == {165300, 165304}


def test_parse_election_search_html_office():
    rows = parsers.parse_election_search_html(ELECTION_SEARCH_HTML)
    president_row = next(r for r in rows if r["election_id"] == 165300)
    assert president_row["office"] == "President"
    assert president_row["district"] == "Statewide"


def test_parse_election_search_html_empty():
    assert parsers.parse_election_search_html("<html></html>") == []


# ---------------------------------------------------------------------------
# parse_bq_search_html
# ---------------------------------------------------------------------------

BQ_SEARCH_HTML = """
<html><body>
<table>
  <tr id="bq-id-11620"><td>2024</td><td>1</td></tr>
  <tr id="bq-id-11621"><td>2024</td><td>2</td></tr>
  <tr id="other-row"><td>skip</td></tr>
</table>
</body></html>
"""


def test_parse_bq_search_html_returns_ids():
    ids = parsers.parse_bq_search_html(BQ_SEARCH_HTML)
    assert set(ids) == {11620, 11621}


def test_parse_bq_search_html_empty():
    assert parsers.parse_bq_search_html("<html></html>") == []


# ---------------------------------------------------------------------------
# parse_bq_metadata_js
# ---------------------------------------------------------------------------

BQ_VIEW_HTML = """
<html><body>
<script>
election_data[11620] = {Election: {
  "id": "11620",
  "question_number": "1",
  "question": "Do you approve of this law?",
  "question_alias": "A - Audit The Legislature",
  "summary": "This proposed law would specify...",
  "is_amendment": "", "is_initiative_petition": "1", "is_referendum": "",
  "is_non_binding": "", "is_local": "", "is_county": "",
  "date": "2024-11-05",
  "year": "2024",
  "n_yes_votes": "2326911", "n_no_votes": "924289", "n_blank_votes": "261730",
  "pct_yes_votes": "0.71570835383858",
  "status": "published"
}};
</script>
</body></html>
"""


def test_parse_bq_metadata_js_fields():
    meta = parsers.parse_bq_metadata_js(BQ_VIEW_HTML)
    assert meta["bq_id"] == 11620
    assert meta["question_number"] == "1"
    assert meta["date"] == "2024-11-05"
    assert meta["n_yes_votes"] == 2326911
    assert meta["is_initiative_petition"] is True
    assert meta["is_local"] is False


def test_parse_bq_metadata_js_not_found():
    result = parsers.parse_bq_metadata_js("<html>no js here</html>")
    assert result == {}


# ---------------------------------------------------------------------------
# parse_election_csv
# ---------------------------------------------------------------------------

ELECTION_CSV = (
    b'City/Town,,,"Harris/ Walz","Trump/ Vance","All Others","Blanks","Total Votes Cast"\r\n'
    b',,,Democratic,Republican,,,\r\n'
    b'Abington,,,"4,714","4,639",4,27,"9,499"\r\n'
    b'Boston,,,"100,000","50,000",10,100,"150,110"\r\n'
    b'TOTALS,,,"104,714","54,639",14,127,"159,609"\r\n'
)


def test_parse_election_csv_columns():
    candidates = parsers.parse_election_csv(ELECTION_CSV)
    names = [c["name"] for c in candidates]
    assert "Harris/ Walz" in names
    assert "Trump/ Vance" in names
    assert "All Others" in names
    assert "Blanks" in names
    assert "Total Votes Cast" in names


def test_parse_election_csv_parties():
    candidates = parsers.parse_election_csv(ELECTION_CSV)
    harris = next(c for c in candidates if c["name"] == "Harris/ Walz")
    assert harris["party"] == "Democratic"
    trump = next(c for c in candidates if c["name"] == "Trump/ Vance")
    assert trump["party"] == "Republican"


def test_parse_election_csv_col_index():
    candidates = parsers.parse_election_csv(ELECTION_CSV)
    harris = next(c for c in candidates if c["name"] == "Harris/ Walz")
    assert harris["col_index"] == 3


def test_parse_election_csv_empty():
    result = parsers.parse_election_csv(b"")
    assert result == []


def test_parse_vote_count_comma_formatted():
    assert parsers._parse_vote_count('"2,041,668"') == 2041668


def test_parse_vote_count_plain():
    assert parsers._parse_vote_count("12345") == 12345


def test_parse_vote_count_empty():
    assert parsers._parse_vote_count("") == 0


# ---------------------------------------------------------------------------
# parse_bq_csv
# ---------------------------------------------------------------------------

BQ_CSV = (
    b'Locality,,,"Yes","No","Blanks","Total Votes Cast"\r\n'
    b'Barnstable,,,"18,328","8,097","1,572","27,997"\r\n'
    b'TOTALS,,,"2,326,911","924,289","261,730","3,512,930"\r\n'
)


def test_parse_bq_csv_totals():
    totals = parsers.parse_bq_csv(BQ_CSV)
    assert totals["Yes"] == 2326911
    assert totals["No"] == 924289
    assert totals["Blanks"] == 261730


def test_parse_bq_csv_empty():
    assert parsers.parse_bq_csv(b"") == {}
