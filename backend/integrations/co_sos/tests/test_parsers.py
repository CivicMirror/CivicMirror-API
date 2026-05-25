"""
Tests for the Colorado SOS HTML parser.
"""
import pytest

from integrations.co_sos.parsers import parse_candidate_table

_HEADER_ROW = (
    "<tr>"
    "<th scope='col'>Candidate name</th>"
    "<th scope='col'>Office</th>"
    "<th scope='col'>District</th>"
    "<th scope='col'>Party</th>"
    "<th scope='col'>Write in?</th>"
    "</tr>"
)


def _build_table(*body_rows: str) -> str:
    rows = _HEADER_ROW + "".join(body_rows)
    return f"<html><body><table>{rows}</table></body></html>"


def _data_row(name, office, district, party, write_in="N", withdrawn=False):
    def cell(value):
        if withdrawn:
            return f"<td><span style='text-decoration: line-through;'>{value}</span></td>"
        return f"<td>{value}</td>"

    return (
        f"<tr>{cell(name)}{cell(office)}{cell(district)}{cell(party)}{cell(write_in)}</tr>"
    )


class TestParseCandidateTable:
    def test_parses_basic_row(self):
        html = _build_table(_data_row("John Smith", "US Senate", "Statewide", "Democratic Party"))
        result = parse_candidate_table(html)
        assert len(result) == 1
        assert result[0]["candidate_name"] == "John Smith"
        assert result[0]["office"] == "US Senate"
        assert result[0]["district"] == "Statewide"
        assert result[0]["party"] == "Democratic Party"
        assert result[0]["is_write_in"] is False
        assert result[0]["is_withdrawn"] is False

    def test_parses_write_in_candidate(self):
        html = _build_table(_data_row("Jane Doe", "Governor", "Statewide", "Unity Party", "Y"))
        result = parse_candidate_table(html)
        assert result[0]["is_write_in"] is True
        assert result[0]["is_withdrawn"] is False

    def test_parses_withdrawn_candidate(self):
        html = _build_table(
            _data_row("Nick Morris", "State Board of Education", "7", "Republican Party", withdrawn=True)
        )
        result = parse_candidate_table(html)
        assert result[0]["is_withdrawn"] is True
        assert result[0]["candidate_name"] == "Nick Morris"

    def test_parses_multiple_rows(self):
        html = _build_table(
            _data_row("Alice", "Governor", "Statewide", "Democratic Party"),
            _data_row("Bob", "Governor", "Statewide", "Republican Party"),
            _data_row("Carol", "US Senate", "Statewide", "Democratic Party"),
        )
        result = parse_candidate_table(html)
        assert len(result) == 3

    def test_returns_empty_list_when_no_table(self):
        result = parse_candidate_table("<html><body>no table here</body></html>")
        assert result == []

    def test_skips_rows_with_empty_candidate_name(self):
        html = _build_table(_data_row("", "Governor", "Statewide", "Democratic Party"))
        result = parse_candidate_table(html)
        assert result == []

    def test_handles_unexpected_header_gracefully(self):
        html = "<html><body><table><tr><th>Col1</th><th>Col2</th></tr></table></body></html>"
        result = parse_candidate_table(html)
        assert result == []

    def test_skips_short_rows(self):
        html = "<html><body><table>" + _HEADER_ROW + "<tr><td>only one cell</td></tr></table></body></html>"
        result = parse_candidate_table(html)
        assert result == []
