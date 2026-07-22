"""
Unit tests for the NC SBE Stage 1 task (sync_nc_elections).
All HTTP calls are mocked — no network access required.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DATE_STRS = ["2024_11_05", "2026_03_03"]


# ---------------------------------------------------------------------------
# sync_nc_elections
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_nc_elections_creates_election_records():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = _DATE_STRS
        sync_nc_elections.apply()

    assert Election.objects.filter(state="NC", election_type="general").exists()
    assert Election.objects.filter(state="NC", election_type="primary").exists()


@pytest.mark.django_db
def test_sync_nc_elections_sets_results_pending_for_past():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = ["2024_11_05"]
        sync_nc_elections.apply()

    election = Election.objects.get(state="NC", election_date=datetime.date(2024, 11, 5))
    assert election.status == Election.Status.RESULTS_PENDING


@pytest.mark.django_db
def test_sync_nc_elections_stores_results_url_in_metadata():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = ["2024_11_05"]
        sync_nc_elections.apply()

    election = Election.objects.get(state="NC", election_date=datetime.date(2024, 11, 5))
    meta = election.source_metadata or {}
    assert "results_url" in meta
    assert "2024_11_05" in meta["results_url"]
    assert meta["nc_date_str"] == "2024_11_05"


@pytest.mark.django_db
def test_sync_nc_elections_skips_pre_2010():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = [
            "1998_05_05", "2024_11_05"
        ]
        result = sync_nc_elections.apply()

    assert Election.objects.filter(state="NC").count() == 1
    assert result.result["skipped"] == 1


@pytest.mark.django_db
def test_sync_nc_elections_is_idempotent():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = _DATE_STRS
        sync_nc_elections.apply()
        sync_nc_elections.apply()

    # Running twice should not duplicate records
    assert Election.objects.filter(state="NC").count() == len(_DATE_STRS)


@pytest.mark.django_db
def test_sync_nc_elections_retries_on_retryable_error():
    from celery.exceptions import Retry

    from integrations.nc_sbe.exceptions import NcSbeRetryableError
    from integrations.nc_sbe.tasks import sync_nc_elections

    with pytest.raises(Retry):
        with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
            MockClient.return_value.list_election_date_strs.side_effect = NcSbeRetryableError("timeout")
            sync_nc_elections.apply()


@pytest.mark.django_db
def test_sync_nc_elections_retries_on_requests_timeout():
    """Network timeouts during S3 listing should be wrapped as NcSbeRetryableError and retried."""
    import requests as req
    from celery.exceptions import Retry

    from integrations.nc_sbe.tasks import sync_nc_elections

    with pytest.raises(Retry):
        with patch("integrations.nc_sbe.client.requests.Session.get", side_effect=req.Timeout("timed out")):
            sync_nc_elections.apply()


# ---------------------------------------------------------------------------
# sync_nc_candidates
# ---------------------------------------------------------------------------

_CANDIDATE_CSV_HEADER = (
    '"election_dt","county_name","contest_name","name_on_ballot","first_name",'
    '"middle_name","last_name","name_suffix_lbl","nick_name","street_address",'
    '"city","state","zip_code","phone","office_phone","business_phone","email",'
    '"candidacy_dt","party_contest","party_candidate","is_unexpired","has_primary",'
    '"is_partisan","vote_for","term"\n'
)


def _candidate_row(
    election_dt, county, contest_name, name, party_contest, party_candidate,
    has_primary="FALSE", is_partisan="TRUE", vote_for="1", term="2",
):
    return (
        f'"{election_dt}","{county}","{contest_name}","{name}","",""'
        f',"","","","PO BOX 1","RALEIGH","NC","27601","","","","x@example.com",'
        f'"12/11/2025","{party_contest}","{party_candidate}","FALSE","{has_primary}",'
        f'"{is_partisan}","{vote_for}","{term}"\n'
    )


def _csv_bytes(*rows: str) -> bytes:
    return (_CANDIDATE_CSV_HEADER + "".join(rows)).encode()


@pytest.mark.django_db
def test_sync_nc_candidates_creates_race_and_dedupes_candidate_across_counties():
    from elections.models import Candidate, Election, Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    election = Election.objects.create(
        state="NC", election_type="primary", election_date=datetime.date(2026, 3, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING, name="2026 NC Primary",
    )
    csv_bytes = _csv_bytes(
        _candidate_row("03/03/2026", "BERTIE", "NC STATE SENATE DISTRICT 01", "Dave Forsythe", "REP", "REP", has_primary="TRUE"),
        _candidate_row("03/03/2026", "CAMDEN", "NC STATE SENATE DISTRICT 01", "Dave Forsythe", "REP", "REP", has_primary="TRUE"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "Elections/2026/Candidate Filing/Candidate_Listing_2026.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()

    race = Race.objects.get(election=election, office_title="NC STATE SENATE DISTRICT 01")
    assert race.source == Race.Source.NC_SBE
    assert Candidate.objects.filter(race=race).count() == 1
    assert Candidate.objects.get(race=race).name == "Dave Forsythe"


@pytest.mark.django_db
def test_sync_nc_candidates_skips_out_of_scope_contest():
    from elections.models import Election, Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    Election.objects.create(
        state="NC", election_type="primary", election_date=datetime.date(2026, 3, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING, name="2026 NC Primary",
    )
    csv_bytes = _csv_bytes(
        _candidate_row("03/03/2026", "BERTIE", "DISTRICT ATTORNEY DISTRICT 01", "Someone", "REP", "REP", has_primary="TRUE"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "key.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()

    assert not Race.objects.filter(office_title="DISTRICT ATTORNEY DISTRICT 01").exists()


@pytest.mark.django_db
def test_sync_nc_candidates_skips_rows_with_no_matching_election():
    from elections.models import Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    # No Election rows exist at all.
    csv_bytes = _csv_bytes(
        _candidate_row("03/03/2026", "BERTIE", "US SENATE", "Someone", "REP", "REP", has_primary="TRUE"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "key.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()

    assert not Race.objects.filter(office_title="US SENATE").exists()


@pytest.mark.django_db
def test_sync_nc_candidates_splits_primary_and_general_into_separate_races():
    from elections.models import Candidate, Election, Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    primary_election = Election.objects.create(
        state="NC", election_type="primary", election_date=datetime.date(2026, 3, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING, name="2026 NC Primary",
    )
    general_election = Election.objects.create(
        state="NC", election_type="general", election_date=datetime.date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING, name="2026 NC General",
    )
    csv_bytes = _csv_bytes(
        _candidate_row("03/03/2026", "BERTIE", "US SENATE", "Dave Forsythe", "REP", "REP", has_primary="TRUE"),
        _candidate_row("11/03/2026", "BERTIE", "US SENATE", "Roy Cooper", "", "DEM", has_primary="FALSE"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "key.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()

    primary_race = Race.objects.get(election=primary_election, office_title="US SENATE")
    general_race = Race.objects.get(election=general_election, office_title="US SENATE")
    assert primary_race.pk != general_race.pk
    assert Candidate.objects.get(race=primary_race).name == "Dave Forsythe"
    assert Candidate.objects.get(race=general_race).name == "Roy Cooper"


@pytest.mark.django_db
def test_sync_nc_candidates_is_idempotent():
    from elections.models import Candidate, Election, Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    Election.objects.create(
        state="NC", election_type="primary", election_date=datetime.date(2026, 3, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING, name="2026 NC Primary",
    )
    csv_bytes = _csv_bytes(
        _candidate_row("03/03/2026", "BERTIE", "US SENATE", "Dave Forsythe", "REP", "REP", has_primary="TRUE"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "key.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()
        sync_nc_candidates.apply()

    assert Race.objects.filter(office_title="US SENATE").count() == 1
    assert Candidate.objects.filter(name="Dave Forsythe").count() == 1
