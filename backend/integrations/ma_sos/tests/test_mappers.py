"""
Tests for integrations.ma_sos.mappers — pure transformation functions.
No DB or HTTP required.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.ma_sos import mappers

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_normalize_basic():
    assert mappers.normalize("  U.S.  House  ") == "u.s. house"


def test_normalize_empty():
    assert mappers.normalize("") == ""


def test_normalize_none():
    assert mappers.normalize(None) == ""


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage,expected", [
    ("General", "general"),
    ("Primaries", "primary"),
    ("Democratic", "primary"),
    ("Republican", "primary"),
    ("Green-Rainbow", "primary"),
    ("Special General", "special"),
    ("", "general"),
])
def test_infer_election_type(stage, expected):
    assert mappers.infer_election_type(stage) == expected


# ---------------------------------------------------------------------------
# party_label_from_stage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage,expected", [
    ("Democratic", "Democratic"),
    ("republican", "Republican"),
    ("Green-Rainbow", "Green-Rainbow"),
    ("General", ""),
    ("Primaries", ""),
    ("", ""),
])
def test_party_label_from_stage(stage, expected):
    assert mappers.party_label_from_stage(stage) == expected


# ---------------------------------------------------------------------------
# contest_variant_key
# ---------------------------------------------------------------------------

def test_contest_variant_key_party_primary():
    key = mappers.contest_variant_key("State Representative", "5th Essex", "Republican")
    assert key == "ma:state representative:5th essex:republican"


def test_contest_variant_key_different_party_different_key():
    dem = mappers.contest_variant_key("State Representative", "5th Essex", "Democratic")
    rep = mappers.contest_variant_key("State Representative", "5th Essex", "Republican")
    assert dem != rep


def test_contest_variant_key_general_is_empty():
    assert mappers.contest_variant_key("State Representative", "5th Essex", "General") == ""


def test_contest_variant_key_generic_primaries_is_empty():
    # Unresolved party (nonpartisan primary caught by the generic "Primaries"
    # fallback stage) — no variant, keeps today's merged-race behavior.
    assert mappers.contest_variant_key("State Representative", "5th Essex", "Primaries") == ""


# ---------------------------------------------------------------------------
# infer_jurisdiction_level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("office,expected", [
    ("U.S. House", "national"),
    ("President", "national"),
    ("Governor", "state"),
    ("State Senate", "state"),
    ("County Commissioner", "state"),
    ("City Council", "local"),
])
def test_infer_jurisdiction_level(office, expected):
    assert mappers.infer_jurisdiction_level(office) == expected


# ---------------------------------------------------------------------------
# infer_geography_scope
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("office,district,expected", [
    ("U.S. House", "1st Congressional", "federal"),
    ("Governor", "", "statewide"),
    ("State Senate", "Norfolk & Plymouth", "district"),
    ("State Representative", "statewide", "statewide"),
])
def test_infer_geography_scope(office, district, expected):
    assert mappers.infer_geography_scope(office, district) == expected


# ---------------------------------------------------------------------------
# parse_ocpf_date
# ---------------------------------------------------------------------------

def test_parse_ocpf_date_valid():
    assert mappers.parse_ocpf_date("11/5/2024") == date(2024, 11, 5)


def test_parse_ocpf_date_empty():
    assert mappers.parse_ocpf_date("") is None


def test_parse_ocpf_date_invalid():
    assert mappers.parse_ocpf_date("not-a-date") is None


# ---------------------------------------------------------------------------
# build_canonical_key
# ---------------------------------------------------------------------------

def test_build_canonical_key():
    key = mappers.build_canonical_key("ma_sos_165323", "U.S. House", "1st Congressional")
    assert key == "ma_sos:ma_sos_165323:u.s. house:1st congressional"


def test_build_canonical_key_no_district():
    key = mappers.build_canonical_key("ma_sos_165300", "President", "")
    assert key == "ma_sos:ma_sos_165300:president:statewide"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_general():
    row = {"election_id": 165300, "office": "President", "district": "Statewide", "stage": "General", "year": 2024}
    schedule = {"primaryElectionDate": "9/3/2024", "generalElectionDate": "11/5/2024"}
    mapped = mappers.map_election(row, schedule)

    assert mapped["source_id"] == "ma_sos_165300"
    assert mapped["state"] == "MA"
    assert mapped["election_type"] == "general"
    assert mapped["election_date"] == date(2024, 11, 5)
    assert mapped["source_metadata"]["electionstats_id"] == 165300
    assert mapped["source_metadata"]["stage"] == "General"


def test_map_election_primary():
    row = {"election_id": 160657, "office": "Governor", "district": "", "stage": "Democratic", "year": 2024}
    schedule = {"primaryElectionDate": "9/3/2024", "generalElectionDate": "11/5/2024"}
    mapped = mappers.map_election(row, schedule)

    assert mapped["election_type"] == "primary"
    assert mapped["election_date"] == date(2024, 9, 3)


def test_map_election_no_schedule():
    row = {"election_id": 165300, "office": "President", "district": "", "stage": "General", "year": 2024}
    mapped = mappers.map_election(row, {})
    assert mapped["election_date"] is None


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def test_map_race_candidate():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_165323"
    mock_election.status = Election.Status.RESULTS_PENDING
    mock_election.source_metadata = {"electionstats_id": 165323}

    election_row = {"election_id": 165323, "office": "U.S. House", "district": "1st Congressional", "stage": "General"}
    result = mappers.map_race(mock_election, election_row)

    assert result["canonical_key"] == "ma_sos:ma_sos_165323:u.s. house:1st congressional"
    assert result["race_type"] == Race.RaceType.CANDIDATE
    assert result["geography_scope"] == "federal"
    assert result["source"] == Race.Source.MA_SOS


def test_map_race_contest_variant_for_party_primary():
    from elections.models import Election
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_171922"
    mock_election.status = Election.Status.RESULTS_PENDING
    mock_election.source_metadata = {"electionstats_id": 171922}

    row = {
        "election_id": 171922, "office": "State Representative",
        "district": "5th Essex", "stage": "Republican",
    }
    result = mappers.map_race(mock_election, row)
    assert result["contest_variant"] == "ma:state representative:5th essex:republican"
    assert result["source_metadata"]["party"] == "Republican"
    assert result["party"] == "Republican"


def test_map_race_no_contest_variant_for_general():
    from elections.models import Election
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_171924"
    mock_election.status = Election.Status.RESULTS_PENDING
    mock_election.source_metadata = {"electionstats_id": 171924}

    row = {
        "election_id": 171924, "office": "State Representative",
        "district": "5th Essex", "stage": "General",
    }
    result = mappers.map_race(mock_election, row)
    assert result["contest_variant"] == ""
    assert result["source_metadata"]["party"] == ""
    assert result["party"] == ""


def test_map_race_includes_canonical_key():
    from elections.models import Election
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_165300"
    mock_election.status = Election.Status.UPCOMING
    mock_election.source_metadata = {"electionstats_id": 165300}

    row = {"election_id": 165300, "office": "President", "district": "", "stage": "General"}
    result = mappers.map_race(mock_election, row)
    assert "canonical_key" in result


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate():
    row = {"name": "Richard E. Neal", "party": "Democratic", "col_index": 3}
    result = mappers.map_candidate(row)
    assert result["party"] == "Democratic"
    assert result["incumbent"] is False
    assert result["source_metadata"]["csv_column_index"] == 3


def test_map_candidate_party_falls_back_to_stage():
    # Primary CSVs don't carry a party row — party comes from the election's
    # per-party stage instead (see issue #105).
    row = {"name": "Christina Delisio", "party": "", "col_index": 1}
    result = mappers.map_candidate(row, stage="Republican")
    assert result["party"] == "Republican"


def test_map_candidate_csv_party_wins_over_stage():
    # General-election CSVs already carry party per-column; stage shouldn't
    # override real data.
    row = {"name": "Vanna Howard", "party": "Democratic", "col_index": 2}
    result = mappers.map_candidate(row, stage="General")
    assert result["party"] == "Democratic"


def test_map_candidate_no_stage_no_party_stays_blank():
    row = {"name": "Some Write-In", "party": "", "col_index": 5}
    result = mappers.map_candidate(row, stage="Primaries")
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_ballot_question
# ---------------------------------------------------------------------------

def test_map_ballot_question():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.status = Election.Status.RESULTS_PENDING

    metadata = {
        "bq_id": 11620,
        "question_number": "1",
        "question": "Do you approve?",
        "question_alias": "A - Audit The Legislature",
        "summary": "Short summary",
        "is_initiative_petition": True,
        "is_referendum": False,
        "is_local": False,
        "is_county": False,
    }
    result = mappers.map_ballot_question(metadata, mock_election)

    assert result["canonical_key"] == "ma_sos:bq_11620"
    assert result["race_type"] == Race.RaceType.MEASURE
    assert result["vote_method"] == Race.VoteMethod.YES_NO
    assert result["office_title"] == "Ballot Question 1"
    assert result["geography_scope"] == "statewide"
    assert result["source_metadata"]["electionstats_bq_id"] == 11620
    assert result["source_metadata"]["is_initiative_petition"] is True


def test_map_ballot_question_local():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.status = Election.Status.UPCOMING

    metadata = {
        "bq_id": 99999,
        "question_number": "A",
        "question": "Local question",
        "question_alias": "",
        "summary": "",
        "is_initiative_petition": False,
        "is_referendum": False,
        "is_local": True,
        "is_county": False,
    }
    result = mappers.map_ballot_question(metadata, mock_election)
    assert result["geography_scope"] == "district"
    assert result["certification_status"] == Race.CertificationStatus.UPCOMING


# ---------------------------------------------------------------------------
# map_ocpf_filer
# ---------------------------------------------------------------------------

_TARR_DEPOSITORY_ROW = {
    "cpfId": 19580,
    "filerName": "Tarr, Andrew",
    "officeSought": "5th Essex",
    "districtCodeSought": 227,
    "districtCodeHeld": 227,
    "receiptsYtdNumeric": 28366.76,
    "expendituresYtdNumeric": 32967.91,
    "currentCashOnHandNumeric": 9824.71,
    "partyAffiliation": "Democratic",
    "isWinner": False,
}

_TARR_FILER_DETAIL = {
    "cpfId": 19580,
    "candidateFirstName": "Andrew",
    "candidateLastName": "Tarr",
    "fullNameReverse": "Tarr, Andrew",
    "fullName": "Andrew F. Tarr",
    "committeeName": "Tarr Committee",
    "candidate": {
        "fullAddress": "215 Washington St Gloucester, MA  01930",
    },
    "officeSought": {
        "districtCode": 227,
        "officeDescription": "House",
        "districtDescription": "5th Essex",
    },
    "partyAffiliation": "Democratic",
    "tags": [
        {"tagTypeDescription": "On Ballot", "year": 2026},
        {"tagTypeDescription": "On Ballot", "year": 2026, "isSpecialElection": True},
    ],
    "filerPhotoUrl": "",
}


def test_map_ocpf_filer_extracts_core_fields():
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, _TARR_FILER_DETAIL)

    assert mapped["ocpf_filer_id"] == "19580"
    assert mapped["name"] == "Andrew F. Tarr"
    assert mapped["family_name"] == "Tarr"
    assert mapped["state"] == "MA"
    assert mapped["chamber"] == "lower"
    assert mapped["district"] == "5th Essex"
    assert mapped["party"] == "Democratic"
    assert mapped["contact_office"] == "215 Washington St Gloucester, MA  01930"
    assert mapped["image_url"] == ""


def test_map_ocpf_filer_extracts_finance_and_ballot_metadata():
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, _TARR_FILER_DETAIL)

    ocpf_meta = mapped["source_metadata"]["ocpf"]
    assert ocpf_meta["cpf_id"] == "19580"
    assert ocpf_meta["committee_name"] == "Tarr Committee"
    assert ocpf_meta["on_ballot"] is True
    assert ocpf_meta["is_winner"] is False
    assert ocpf_meta["receipts_ytd"] == 28366.76
    assert ocpf_meta["expenditures_ytd"] == 32967.91
    assert ocpf_meta["cash_on_hand"] == 9824.71


def test_map_ocpf_filer_senate_chamber():
    detail = {**_TARR_FILER_DETAIL, "officeSought": {"officeDescription": "Senate", "districtDescription": "1st Essex & Middlesex"}}
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, detail)
    assert mapped["chamber"] == "upper"
    assert mapped["district"] == "1st Essex & Middlesex"


def test_map_ocpf_filer_falls_back_to_depository_name_when_detail_missing():
    """If the /filer/{cpfId} call failed (detail={}), depository_row's
    "Last, First" filerName should still produce a usable name for matching."""
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, {})

    assert mapped["name"] == "Andrew Tarr"
    assert mapped["chamber"] == ""
    assert mapped["contact_office"] == ""
    assert mapped["ocpf_filer_id"] == "19580"


def test_map_ocpf_filer_no_photo_is_empty_string_not_none():
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, _TARR_FILER_DETAIL)
    assert mapped["image_url"] == ""


def test_map_ocpf_filer_with_photo():
    detail = {**_TARR_FILER_DETAIL, "filerPhotoUrl": "https://ocpf2.blob.core.windows.net/filers-photos/thumbnail/11916_thumbnail.jpg"}
    mapped = mappers.map_ocpf_filer(_TARR_DEPOSITORY_ROW, detail)
    assert mapped["image_url"].startswith("https://ocpf2.blob.core.windows.net")


def test_map_ocpf_filer_challenger_no_office_held():
    """Christina Delisio: on-ballot challenger, no officeHeld — same shape,
    should map cleanly with no incumbency-related fields required."""
    depository_row = {
        "cpfId": 19596,
        "filerName": "Delisio, Christina",
        "officeSought": "5th Essex",
        "receiptsYtdNumeric": 15630.83,
        "expendituresYtdNumeric": 17963.49,
        "currentCashOnHandNumeric": 1510.95,
        "partyAffiliation": "Republican",
        "isWinner": False,
    }
    detail = {
        "cpfId": 19596,
        "candidateFirstName": "Christina",
        "candidateLastName": "Delisio",
        "fullName": "Christina S. Delisio",
        "committeeName": "Delisio Committee",
        "candidate": {"fullAddress": "6 Lincoln Ave Manchester, MA  01944"},
        "officeSought": {"officeDescription": "House", "districtDescription": "5th Essex"},
        "officeHeld": {"districtCode": 0, "officeDescription": "N/A"},
        "partyAffiliation": "Republican",
        "tags": [{"tagTypeDescription": "On Ballot", "year": 2026}],
        "filerPhotoUrl": "",
    }

    mapped = mappers.map_ocpf_filer(depository_row, detail)

    assert mapped["name"] == "Christina S. Delisio"
    assert mapped["family_name"] == "Delisio"
    assert mapped["party"] == "Republican"
    assert mapped["contact_office"] == "6 Lincoln Ave Manchester, MA  01944"
    assert mapped["source_metadata"]["ocpf"]["on_ballot"] is True
