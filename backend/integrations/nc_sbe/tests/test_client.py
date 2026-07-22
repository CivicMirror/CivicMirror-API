"""
Unit tests for the NC SBE Candidate Filing CSV client helpers.
All HTTP calls are mocked — no network access required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

_LIST_CANDIDATE_FILING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>dl.ncsbe.gov</Name>
    <Prefix>Elections/2026/Candidate Filing/</Prefix>
    <IsTruncated>false</IsTruncated>
    <Contents>
        <Key>Elections/2026/Candidate Filing/</Key>
    </Contents>
    <Contents>
        <Key>Elections/2026/Candidate Filing/Candidate_Listing_2026.csv</Key>
    </Contents>
</ListBucketResult>
"""

_LIST_EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>dl.ncsbe.gov</Name>
    <Prefix>Elections/2009/Candidate Filing/</Prefix>
    <IsTruncated>false</IsTruncated>
</ListBucketResult>
"""

_SAMPLE_CSV = (
    b'"election_dt","county_name","contest_name","name_on_ballot","first_name",'
    b'"middle_name","last_name","name_suffix_lbl","nick_name","street_address",'
    b'"city","state","zip_code","phone","office_phone","business_phone","email",'
    b'"candidacy_dt","party_contest","party_candidate","is_unexpired","has_primary",'
    b'"is_partisan","vote_for","term"\n'
    b'"03/03/2026","BERTIE","NC STATE SENATE DISTRICT 01","Dave Forsythe","DAVE","",'
    b'"FORSYTHE","","","PO BOX 1","RALEIGH","NC","27601","","","","d@example.com",'
    b'"12/11/2025","REP","REP","FALSE","TRUE","TRUE","1","2"\n'
    b'"03/03/2026","CAMDEN","NC STATE SENATE DISTRICT 01","Dave Forsythe","DAVE","",'
    b'"FORSYTHE","","","PO BOX 1","RALEIGH","NC","27601","","","","d@example.com",'
    b'"12/11/2025","REP","REP","FALSE","TRUE","TRUE","1","2"\n'
)


def _mock_response(content: bytes, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# list_candidate_filing_csv_key
# ---------------------------------------------------------------------------

def test_list_candidate_filing_csv_key_returns_csv_key():
    from integrations.nc_sbe.client import NcSbeClient

    client = NcSbeClient()
    with patch.object(client, "_get", return_value=_mock_response(_LIST_CANDIDATE_FILING_XML.encode())):
        key = client.list_candidate_filing_csv_key("2026")

    assert key == "Elections/2026/Candidate Filing/Candidate_Listing_2026.csv"


def test_list_candidate_filing_csv_key_returns_none_when_absent():
    from integrations.nc_sbe.client import NcSbeClient

    client = NcSbeClient()
    with patch.object(client, "_get", return_value=_mock_response(_LIST_EMPTY_XML.encode())):
        key = client.list_candidate_filing_csv_key("2009")

    assert key is None


# ---------------------------------------------------------------------------
# fetch_candidate_filing_csv
# ---------------------------------------------------------------------------

def test_fetch_candidate_filing_csv_gets_key_url():
    from integrations.nc_sbe.client import NcSbeClient

    client = NcSbeClient()
    with patch.object(client, "_get", return_value=_mock_response(b"csv-bytes")) as mock_get:
        content = client.fetch_candidate_filing_csv("Elections/2026/Candidate Filing/Candidate_Listing_2026.csv")

    assert content == b"csv-bytes"
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith("Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv")


# ---------------------------------------------------------------------------
# parse_candidate_listing_csv
# ---------------------------------------------------------------------------

def test_parse_candidate_listing_csv_returns_row_dicts():
    from integrations.nc_sbe.client import parse_candidate_listing_csv

    rows = parse_candidate_listing_csv(_SAMPLE_CSV)

    assert len(rows) == 2
    assert rows[0]["contest_name"] == "NC STATE SENATE DISTRICT 01"
    assert rows[0]["county_name"] == "BERTIE"
    assert rows[0]["name_on_ballot"] == "Dave Forsythe"
    assert rows[0]["party_contest"] == "REP"
    assert rows[0]["vote_for"] == "1"


def test_parse_candidate_listing_csv_empty_bytes_returns_empty_list():
    from integrations.nc_sbe.client import parse_candidate_listing_csv

    assert parse_candidate_listing_csv(b"") == []
