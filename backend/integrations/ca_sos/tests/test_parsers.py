"""Tests for CA SOS CSV catalog parsers."""
import pytest

from integrations.ca_sos.parsers import (
    deduplicate_catalog,
    parse_api_endpoint_catalog,
    parse_election_date_from_catalog,
    parse_endpoint_catalog,
)

SAMPLE_CSV = b"""RaceID,ContestName,EndpointURL,ContestType
02000000000059,Governor - Statewide Results,/returns/governor,Candidate
02000000000062,Lieutenant Governor - Statewide Results,/returns/lieutenant-governor,Candidate
,Ballot Measures - Statewide Results,/returns/ballot-measures,Measure
,Proposition 1,/returns/proposition-01,Measure
,,/returns/status,
02,US Senate,,Candidate
"""


class TestParseEndpointCatalog:
    def test_parses_standard_csv(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        paths = [e["path"] for e in entries]
        assert "/returns/governor" in paths
        assert "/returns/lieutenant-governor" in paths
        assert "/returns/ballot-measures" in paths
        assert "/returns/proposition-01" in paths

    def test_skips_status_endpoint(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        paths = [e["path"] for e in entries]
        assert "/returns/status" not in paths

    def test_skips_empty_path(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        paths = [e["path"] for e in entries]
        assert "" not in paths
        assert "/" not in paths

    def test_measure_type_detection(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        measures = [e for e in entries if e["type"] == "measure"]
        candidates = [e for e in entries if e["type"] == "candidate"]
        measure_paths = [e["path"] for e in measures]
        assert "/returns/ballot-measures" in measure_paths
        assert "/returns/proposition-01" in measure_paths
        assert len(candidates) >= 2

    def test_race_id_populated(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        governor = next(e for e in entries if e["path"] == "/returns/governor")
        assert governor["race_id"] == "02000000000059"

    def test_race_id_empty_when_missing(self):
        entries = parse_endpoint_catalog(SAMPLE_CSV)
        measures = [e for e in entries if e["path"] == "/returns/ballot-measures"]
        assert measures[0]["race_id"] == ""

    def test_empty_bytes_returns_empty_list(self):
        entries = parse_endpoint_catalog(b"")
        assert entries == []

    def test_handles_utf8_bom(self):
        csv_with_bom = b"\xef\xbb\xbfRaceID,ContestName,EndpointURL,ContestType\n01,Gov,/returns/governor,Candidate\n"
        entries = parse_endpoint_catalog(csv_with_bom)
        assert len(entries) == 1
        assert entries[0]["path"] == "/returns/governor"

    def test_skips_pdf_and_csv_paths(self):
        csv_data = b"RaceID,ContestName,EndpointURL,ContestType\n,Doc,/media/results.pdf,\n,Data,/media/data.csv,\n,Gov,/returns/governor,Candidate\n"
        entries = parse_endpoint_catalog(csv_data)
        paths = [e["path"] for e in entries]
        assert "/returns/governor" in paths
        assert "/media/results.pdf" not in paths
        assert "/media/data.csv" not in paths


class TestDeduplicateCatalog:
    def test_removes_duplicate_paths(self):
        entries = [
            {"path": "/returns/governor", "name": "Governor 1", "type": "candidate", "race_id": "1"},
            {"path": "/returns/governor", "name": "Governor 2", "type": "candidate", "race_id": "2"},
            {"path": "/returns/senate", "name": "Senate", "type": "candidate", "race_id": "3"},
        ]
        result = deduplicate_catalog(entries)
        assert len(result) == 2
        paths = [e["path"] for e in result]
        assert paths.count("/returns/governor") == 1

    def test_preserves_order(self):
        entries = [
            {"path": "/a", "name": "A", "type": "candidate", "race_id": ""},
            {"path": "/b", "name": "B", "type": "candidate", "race_id": ""},
        ]
        result = deduplicate_catalog(entries)
        assert [e["path"] for e in result] == ["/a", "/b"]


SAMPLE = b"""https://api.sos.ca.gov
"|This file lists all available endpoints for the California June 2, 2026 Primary Election|"

https://api.sos.ca.gov/returns/governor
https://api.sos.ca.gov/returns/governor/county/alameda

https://api.sos.ca.gov/returns/us-rep/district/all
https://api.sos.ca.gov/returns/us-rep/district/12

https://api.sos.ca.gov/returns/status
"""


def test_parse_api_catalog_keeps_statewide_and_district_skips_county():
    entries = parse_api_endpoint_catalog(SAMPLE)
    paths = [e["path"] for e in entries]
    assert "/returns/governor" in paths
    assert "/returns/us-rep/district/12" in paths
    assert "/returns/governor/county/alameda" not in paths   # county skipped
    assert "/returns/us-rep/district/all" not in paths        # 'all' skipped
    assert "/returns/status" not in paths                     # status skipped


def test_parse_api_catalog_names_default_to_path_tail():
    entries = parse_api_endpoint_catalog(SAMPLE)
    gov = next(e for e in entries if e["path"] == "/returns/governor")
    assert gov["name"].lower() == "governor"


def test_parse_election_date_from_catalog_title():
    assert parse_election_date_from_catalog(SAMPLE).isoformat() == "2026-06-02"


def test_parse_election_date_returns_none_when_absent():
    assert parse_election_date_from_catalog(b"https://api.sos.ca.gov\nno date here\n") is None
