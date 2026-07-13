import json
import os
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election
from results.adapters.nj import NewJerseyAdapter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_json_fixture(name: str):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _mock_proxy_get_for_counties(county_payloads: dict[str, list]):
    """
    Returns a function usable as proxy_get's side_effect: routes
    current_ver.txt requests to a fixed fake version, and summary.json
    requests to the matching county's fixture payload.
    """
    def _side_effect(url, **kwargs):
        for county_name, payload in county_payloads.items():
            if county_name.lower() in url.lower():
                if url.endswith("current_ver.txt"):
                    return MagicMock(status_code=200, text="999", raise_for_status=lambda: None)
                if url.endswith("summary.json"):
                    resp = MagicMock(status_code=200, raise_for_status=lambda: None)
                    resp.json.return_value = payload
                    return resp
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _side_effect


@pytest.mark.django_db
def test_fetch_results_aggregates_us_senate_across_counties_with_different_naming():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")
    burlington_payload = _load_json_fixture("nj_burlington_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
                {"county": "Burlington", "url": "https://results.enr.clarityelections.com/NJ/Burlington/126521/", "election_id": "126521"},
            ],
        },
    )

    adapter = NewJerseyAdapter()
    with patch(
        "results.adapters.nj.proxy_get",
        side_effect=_mock_proxy_get_for_counties({
            "Atlantic": atlantic_payload,
            "Burlington": burlington_payload,
        }),
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    senate_dem_rows = [r for r in result.rows if r.office_title == "UNITED STATES SENATOR (DEM PRIMARY)"]
    assert senate_dem_rows, "expected aggregated DEM US Senate rows despite differing office titles per county"

    booker_row = next(r for r in senate_dem_rows if r.candidate_name == "CORY BOOKER")
    # Atlantic's "DEM U.S. Senator" -> Cory BOOKER (14931 votes) and
    # Burlington's "US Senate (DEM)" -> Cory Booker (35480 votes) must have
    # summed into ONE row of 50411, not two separate rows.
    assert booker_row.vote_count == 14931 + 35480

    # No duplicate candidate rows for the same normalized name within one office/party.
    names_seen = [r.candidate_name for r in senate_dem_rows]
    assert len(names_seen) == len(set(names_seen))

    # Burlington's "Personal Choice" write-in line must not appear as a candidate.
    assert "PERSONAL CHOICE" not in names_seen


@pytest.mark.django_db
def test_fetch_results_keeps_dem_and_rep_primaries_as_separate_races():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_2",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
            ],
        },
    )

    adapter = NewJerseyAdapter()
    with patch(
        "results.adapters.nj.proxy_get",
        side_effect=_mock_proxy_get_for_counties({"Atlantic": atlantic_payload}),
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    office_titles = {r.office_title for r in result.rows if "SENATOR" in (r.office_title or "")}
    assert "UNITED STATES SENATOR (DEM PRIMARY)" in office_titles
    assert "UNITED STATES SENATOR (REP PRIMARY)" in office_titles

    # Candidates must not leak across the two parties' rows.
    dem_names = {r.candidate_name for r in result.rows if r.office_title == "UNITED STATES SENATOR (DEM PRIMARY)"}
    rep_names = {r.candidate_name for r in result.rows if r.office_title == "UNITED STATES SENATOR (REP PRIMARY)"}
    assert dem_names == {"CORY BOOKER"}
    assert rep_names == {"ROBERT S. LEBOVICS", "JUSTIN MURPHY", "ALEX ZDAN", "RICHARD TABOR"}


@pytest.mark.django_db
def test_fetch_results_returns_empty_when_no_county_urls():
    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_3",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={},
    )

    adapter = NewJerseyAdapter()
    result = adapter.fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"


@pytest.mark.django_db
def test_fetch_results_skips_county_that_fails_without_aborting():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_4",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
                {"county": "BrokenCounty", "url": "https://results.enr.clarityelections.com/NJ/BrokenCounty/999/", "election_id": "999"},
            ],
        },
    )

    def _side_effect(url, **kwargs):
        if "brokencounty" in url.lower():
            raise __import__("requests").exceptions.ConnectionError("simulated failure")
        return _mock_proxy_get_for_counties({"Atlantic": atlantic_payload})(url, **kwargs)

    adapter = NewJerseyAdapter()
    with patch("results.adapters.nj.proxy_get", side_effect=_side_effect):
        result = adapter.fetch_results(election.election_date, election.pk)

    # BrokenCounty failing must not prevent Atlantic's rows from being returned.
    assert result.rows
    assert "counties_polled=1/2" in (result.notes or "")
