import csv
import io
from datetime import date
from unittest.mock import patch

import pytest

from elections.models import Election, Race
from integrations.nc_sbe.classification import classify_nc_contest
from results.adapters.nc import _aggregate_rows
from results.tests.test_nc_identity import raw


@pytest.mark.django_db
def test_jurisdiction_events_remain_stable_across_confidence_and_repeated_ingestion():
    from integrations.nc_sbe.event_identity import ensure_event

    day = date(2025, 11, 4)
    inferred = classify_nc_contest(day, "CITY OF ROCKY MOUNT MAYOR")
    confirmed = classify_nc_contest(day, "CITY OF ROCKY MOUNT MAYOR", municipal_method="plurality")
    one, created = ensure_event(day, inferred)
    two, created_again = ensure_event(day, confirmed)
    assert created and not created_again
    assert one.pk == two.pk
    assert two.election_type == "municipal"
    assert two.jurisdiction_level == "local"
    assert two.source_metadata["nc_classification"]["evidence_status"] == "confirmed"
    assert Election.objects.count() == 1


@pytest.mark.django_db
def test_date_zip_is_filtered_before_empty_municipal_event_bootstrap():
    from integrations.nc_sbe.event_identity import ensure_event, filter_result_rows
    from results.adapters.base import AdapterResult
    from results.tasks import _bootstrap_races_from_results

    day = date(2024, 11, 5)
    event, _ = ensure_event(day, classify_nc_contest(day, "CITY OF ASHEVILLE MAYOR"))
    rows = _aggregate_rows(
        [
            raw(kind="S", title="NC GOVERNOR", county="WAKE"),
            raw(kind="C", title="CITY OF ASHEVILLE MAYOR", county="BUNCOMBE", code="200"),
        ]
    )
    scoped = filter_result_rows(event, rows)
    assert [r.office_title for r in scoped] == ["CITY OF ASHEVILLE MAYOR"]
    _bootstrap_races_from_results(event, AdapterResult(scoped, "https://example.org/results.zip", "full"), "NC")
    assert list(event.races.values_list("office_title", flat=True)) == ["CITY OF ASHEVILLE MAYOR"]


@pytest.mark.django_db
def test_file_hints_route_unexpired_contest_even_when_result_title_omits_marker():
    from integrations.nc_sbe.event_identity import ensure_event, filter_result_rows

    day = date(2026, 11, 3)
    title = "US HOUSE OF REPRESENTATIVES DISTRICT 03"
    ordinary, _ = ensure_event(day, classify_nc_contest(day, title))
    special, _ = ensure_event(day, classify_nc_contest(day, title, is_unexpired=True))
    Race.objects.create(
        election=special,
        office_title=title,
        race_type="candidate",
        source="nc_sbe",
        source_metadata={"is_unexpired": True, "party_contest": ""},
    )
    rows = _aggregate_rows([raw(kind="S", title=title, county="WAKE")])
    assert filter_result_rows(ordinary, rows) == []
    assert len(filter_result_rows(special, rows)) == 1


@pytest.mark.django_db
def test_candidate_sync_separates_special_context_and_preserves_repeat_identity():
    from integrations.nc_sbe.tasks import sync_nc_candidates

    day = date(2026, 3, 3)
    Election.objects.create(
        name="NC primary",
        state="NC",
        election_date=day,
        election_type="primary",
        jurisdiction_level="state",
        status="upcoming",
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "election_dt",
            "contest_name",
            "party_contest",
            "name_on_ballot",
            "party_candidate",
            "is_unexpired",
            "is_partisan",
            "vote_for",
            "term",
        ],
    )
    writer.writeheader()
    for suffix, flag, name in [("", "FALSE", "Alice"), (" (UNEXPIRED)", "TRUE", "Bob")]:
        writer.writerow(
            {
                "election_dt": "03/03/2026",
                "contest_name": "US HOUSE OF REPRESENTATIVES DISTRICT 03" + suffix,
                "party_contest": "REP",
                "name_on_ballot": name,
                "party_candidate": "REP",
                "is_unexpired": flag,
                "is_partisan": "TRUE",
                "vote_for": "1",
                "term": "2",
            }
        )
    with patch("integrations.nc_sbe.tasks.NcSbeClient") as client:
        client.return_value.list_candidate_filing_csv_key.return_value = "filings.csv"
        client.return_value.fetch_candidate_filing_csv.return_value = output.getvalue().encode()
        sync_nc_candidates.apply().get()
        before = list(Race.objects.order_by("pk").values_list("pk", "election_id", "canonical_key"))
        sync_nc_candidates.apply().get()
    races = list(Race.objects.select_related("election").order_by("pk"))
    assert len(races) == 2
    assert races[0].election_id != races[1].election_id
    assert races[1].source_metadata["nc_classification"]["special_context"] is True
    assert races[1].election.election_type == "primary"
    assert before == list(Race.objects.order_by("pk").values_list("pk", "election_id", "canonical_key"))


@pytest.mark.django_db
def test_discovery_seeds_known_upcoming_dates_without_results_prefix():
    from integrations.nc_sbe.tasks import sync_nc_elections

    with (
        patch("integrations.nc_sbe.tasks.NcSbeClient") as client,
        patch("integrations.nc_sbe.tasks.timezone.localdate", return_value=date(2026, 1, 2)),
    ):
        client.return_value.list_election_date_strs.return_value = []
        sync_nc_elections.apply().get()
    assert Election.objects.filter(state="NC", election_date=date(2026, 3, 3), election_type="primary").exists()
    assert Election.objects.filter(state="NC", election_date=date(2026, 11, 3), election_type="general").exists()


@pytest.mark.django_db
def test_classification_and_file_hint_changes_invalidate_results_cache():
    from integrations.nc_sbe.event_identity import ensure_event
    from results.adapters.nc import NorthCarolinaAdapter

    day = date(2026, 11, 3)
    election, _ = ensure_event(day, classify_nc_contest(day, "US SENATE"))
    before = NorthCarolinaAdapter().version_cache_key(election.pk)
    Race.objects.create(
        election=election,
        office_title="US SENATE",
        race_type="candidate",
        source="nc_sbe",
        source_metadata={"is_unexpired": True},
    )
    assert NorthCarolinaAdapter().version_cache_key(election.pk) != before


@pytest.mark.django_db
def test_future_municipal_election_is_discovered_from_filings_without_creating_races():
    from integrations.nc_sbe.tasks import sync_nc_elections

    payload = (
        b"election_dt,county_name,contest_name,party_contest,is_unexpired\n11/02/2027,WAKE,TOWN OF CARY MAYOR,,FALSE\n"
    )
    with (
        patch("integrations.nc_sbe.tasks.NcSbeClient") as client,
        patch("integrations.nc_sbe.tasks.timezone.localdate", return_value=date(2027, 10, 1)),
    ):
        client.return_value.list_election_date_strs.return_value = ["2027_11_02"]
        client.return_value.list_candidate_filing_csv_key.return_value = "filings.csv"
        client.return_value.fetch_candidate_filing_csv.return_value = payload
        sync_nc_elections.apply().get()
    event = Election.objects.get(state="NC", election_type="municipal")
    assert event.source_metadata["nc_classification"]["phase"] == "general"
    assert event.source_metadata["nc_classification"]["evidence_status"] == "inferred"
    assert not Race.objects.exists()
