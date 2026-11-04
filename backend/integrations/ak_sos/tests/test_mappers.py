"""
Unit tests for integrations.ak_sos.mappers, run against real fixture HTML
pulled live from elections.alaska.gov/election-candidates/ on 2026-11-03
(see tests/fixtures/*.html). No network calls.
"""
from pathlib import Path

import pytest

from integrations.ak_sos.mappers import (
    candidate_status_for,
    map_candidate,
    map_race_identity,
    normalize_candidate_name,
    office_title_for,
    parse_candidates_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# office_title_for
# ---------------------------------------------------------------------------

def test_office_title_for_governor():
    assert office_title_for("GOVERNOR / LIEUTENANT GOVERNOR") == "Governor / Lieutenant Governor"


def test_office_title_for_us_senator():
    assert office_title_for("UNITED STATES SENATOR") == "U.S. Senator"


def test_office_title_for_us_representative():
    assert office_title_for("UNITED STATES REPRESENTATIVE") == "U.S. Representative"


def test_office_title_for_house_strips_zero_padding():
    assert office_title_for("STATE HOUSE DISTRICT 01") == "State House - District 1"
    assert office_title_for("STATE HOUSE DISTRICT 40") == "State House - District 40"


def test_office_title_for_senate_keeps_letter():
    assert office_title_for("STATE SENATE DISTRICT A") == "State Senate - District A"


def test_office_title_for_out_of_scope_intro_headings():
    assert office_title_for("Upcoming State Elections") is None
    assert office_title_for("How to File Your Candidacy") is None


def test_office_title_for_judicial_out_of_scope():
    assert office_title_for("SUPREME COURT") is None
    assert office_title_for("DISTRICT COURT") is None


# ---------------------------------------------------------------------------
# normalize_candidate_name
# ---------------------------------------------------------------------------

def test_normalize_candidate_name_reverses_last_first():
    assert normalize_candidate_name("Bynum, Jeremy T.", "State House - District 1") == "Jeremy T. Bynum"


def test_normalize_candidate_name_no_comma_passthrough():
    assert normalize_candidate_name("Will Stapp", "State House - District 32") == "Will Stapp"


def test_normalize_candidate_name_governor_ticket_reduces_to_surnames():
    # Must match the bare "Surname/Surname" form results/adapters/ak.py's
    # ENR feed uses, or results rows can never attach to this candidate.
    assert (
        normalize_candidate_name("Bronson, Dave / Church, Josh", "Governor / Lieutenant Governor")
        == "Bronson/Church"
    )


def test_normalize_candidate_name_governor_ticket_with_nickname_and_suffix():
    assert (
        normalize_candidate_name(
            'Kroll, Henry F. "Hank" / Nicholson, Tommy R. III', "Governor / Lieutenant Governor",
        )
        == "Kroll/Nicholson"
    )


# ---------------------------------------------------------------------------
# candidate_status_for
# ---------------------------------------------------------------------------

def test_candidate_status_withdrawn_overrides_status_text():
    assert candidate_status_for("Certified", withdrawn=True) == "withdrawn"


def test_candidate_status_certified_is_running():
    assert candidate_status_for("Certified", withdrawn=False) == "running"


def test_candidate_status_denied_is_disqualified():
    assert candidate_status_for("Denied", withdrawn=False) == "disqualified"


def test_candidate_status_denied_with_appended_note_is_disqualified():
    # Observed live data quirk: a second note glued on with no separator.
    assert candidate_status_for("DeniedNo POFD on file", withdrawn=False) == "disqualified"


def test_candidate_status_unknown_defaults_to_running():
    assert candidate_status_for("", withdrawn=False) == "running"


# ---------------------------------------------------------------------------
# parse_candidates_html — against real fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture", [
    "governor.html", "state_senator.html", "state_representative.html",
    "us_senator.html", "us_representative.html",
])
def test_parse_candidates_html_same_53_offices_regardless_of_search_contest(fixture):
    # Confirmed live: the Contest field has no effect on what's returned.
    records = parse_candidates_html(_fixture(fixture))
    offices = {r["office_title"] for r in records}
    assert len(offices) == 53
    assert "Governor / Lieutenant Governor" in offices
    assert "U.S. Senator" in offices
    assert "U.S. Representative" in offices
    assert "State House - District 1" in offices
    assert "State Senate - District A" in offices


def test_parse_candidates_html_governor_ticket_fields():
    records = parse_candidates_html(_fixture("governor.html"))
    bronson = next(r for r in records if r["ballot_name"] == "Bronson, Dave / Church, Josh")
    assert bronson["name"] == "Bronson/Church"
    assert bronson["office_title"] == "Governor / Lieutenant Governor"
    assert bronson["party"] == "Registered Republican"
    assert bronson["candidate_status"] == "running"
    assert bronson["email"] == "info@davebronson.com"


def test_parse_candidates_html_withdrawn_candidate():
    records = parse_candidates_html(_fixture("governor.html"))
    claman = next(r for r in records if "Claman" in r["ballot_name"])
    assert claman["withdrawn"] is True
    assert claman["candidate_status"] == "withdrawn"


def test_parse_candidates_html_incumbent_flag():
    records = parse_candidates_html(_fixture("state_representative.html"))
    bynum = next(r for r in records if r["name"] == "Jeremy T. Bynum")
    assert bynum["incumbent"] is True
    assert bynum["office_title"] == "State House - District 1"


def test_parse_candidates_html_no_duplicate_intro_sections():
    records = parse_candidates_html(_fixture("governor.html"))
    assert all(r["office_title"] for r in records)


# ---------------------------------------------------------------------------
# map_race_identity / map_candidate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_map_race_identity_governor_is_statewide():
    identity, fields = map_race_identity("Governor / Lieutenant Governor")
    assert identity["office_title"] == "Governor / Lieutenant Governor"
    assert fields["geography_scope"] == "statewide"
    assert fields["source"] == "ak_sos"


@pytest.mark.django_db
def test_map_race_identity_us_senator_is_federal():
    _, fields = map_race_identity("U.S. Senator")
    assert fields["geography_scope"] == "federal"


@pytest.mark.django_db
def test_map_race_identity_house_district_is_district():
    _, fields = map_race_identity("State House - District 1")
    assert fields["geography_scope"] == "district"


def test_map_candidate_fields():
    record = {
        "candidate_status": "running", "incumbent": True, "phone": "(907) 555-1234",
        "address": "PO Box 1 Juneau, AK 99801", "status_raw": "Certified",
        "ballot_name": "Doe, Jane", "email": "jane@example.com",
    }
    fields = map_candidate(record)
    assert fields["candidate_status"] == "running"
    assert fields["incumbent"] is True
    assert fields["contact_phone"] == "(907) 555-1234"
    assert fields["contact_office"] == "PO Box 1 Juneau, AK 99801"
    assert fields["source_metadata"]["email"] == "jane@example.com"
