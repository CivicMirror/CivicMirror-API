from datetime import date

import pytest

from elections.models import Candidate, Election, Race
from results.adapters.base import AdapterResult
from results.adapters.nc import _aggregate_rows
from results.models import OfficialResult
from results.tasks import _bootstrap_races_from_results, _process_race_results
from results.winners import derive_winners


def raw(county="ALAMANCE", title="SHERIFF", code="1", choice="Alice", party="DEM", seats="1", votes=10, kind="C"):
    return {
        "Election Date": "11/05/2024",
        "County": county,
        "Contest Name": title,
        "Contest Group ID": code,
        "Choice": choice,
        "Choice Party": party,
        "Vote For": seats,
        "Total Votes": str(votes),
        "Contest Type": kind,
    }


def election():
    return Election.objects.create(
        name="NC 2024", state="NC", election_date=date(2024, 11, 5), election_type="general", jurisdiction_level="state"
    )


def test_county_collisions_and_general_party_do_not_define_same_identity():
    rows = _aggregate_rows([raw(), raw(choice="Bob", party="REP"), raw(county="ORANGE", votes=30)])
    assert len(rows) == 3
    assert rows[0].raw["nc_contest_key"] == rows[1].raw["nc_contest_key"]
    assert rows[0].raw["nc_contest_key"] != rows[2].raw["nc_contest_key"]
    assert rows[0].raw["party"] == "DEM"
    assert rows[1].raw["party"] == "REP"
    assert all(r.jurisdiction_fragment == "" for r in rows)


def test_multicounty_district_is_one_contest():
    rows = _aggregate_rows(
        [
            raw(kind="S", title="NC STATE SENATE DISTRICT 01"),
            raw(kind="S", title="NC STATE SENATE DISTRICT 01", county="ORANGE", votes=30),
        ]
    )
    assert len(rows) == 1
    assert rows[0].vote_count == 40
    assert rows[0].raw["reporting_counties"] == ["ALAMANCE", "ORANGE"]


def test_verified_multicounty_local_electorate_is_not_county_split():
    rows = _aggregate_rows(
        [
            raw(title="CITY OF RALEIGH MAYOR", code="920015", county="DURHAM"),
            raw(title="CITY OF RALEIGH MAYOR", code="920015", county="WAKE", votes=30),
        ]
    )
    assert len(rows) == 1
    assert rows[0].vote_count == 40
    assert rows[0].raw["nc_electorate"] == "municipality:RALEIGH"
    assert rows[0].raw["nc_identity_verified"] is True


def test_unknown_multicounty_municipality_stays_unresolved():
    rows = _aggregate_rows(
        [raw(title="CITY OF SPRINGFIELD MAYOR"), raw(title="CITY OF SPRINGFIELD MAYOR", county="ORANGE")]
    )
    assert all(r.raw["nc_identity_verified"] is False for r in rows)


@pytest.mark.django_db
def test_bootstrap_persists_contest_without_splitting_general_parties():
    e = election()
    result = AdapterResult(
        _aggregate_rows([raw(), raw(choice="Bob", party="REP")]), "https://example.org/nc.zip", "full"
    )
    races = _bootstrap_races_from_results(e, result, "NC")
    assert len(races) == 1
    race = races[0]
    assert dict(race.candidates.values_list("name", "party")) == {"Alice": "DEM", "Bob": "REP"}
    assert race.source_metadata["source_vote_for"] == 1
    assert race.source_metadata["nc_contest_key"] == result.rows[0].raw["nc_contest_key"]
    assert not race.party


@pytest.mark.django_db
def test_bootstrap_types_generic_named_for_against_contest_as_measure():
    e = election()
    result = AdapterResult(
        _aggregate_rows(
            [
                raw(title="DUPLIN COUNTY UNFORTIFIED WINE ELECTION", choice="FOR", party=""),
                raw(title="DUPLIN COUNTY UNFORTIFIED WINE ELECTION", choice="AGAINST", party=""),
            ]
        ),
        "https://example.org/nc.zip",
        "full",
    )

    races = _bootstrap_races_from_results(e, result, "NC")

    assert len(races) == 1
    assert races[0].race_type == Race.RaceType.MEASURE
    assert set(races[0].measure_options.values_list("option_label", flat=True)) == {"FOR", "AGAINST"}
    assert races[0].candidates.count() == 0
    _process_race_results(races[0], result, "NC")
    assert OfficialResult.objects.filter(race=races[0], measure_option__isnull=False).count() == 2
    races[0].certification_status = Race.CertificationStatus.RESULTS_CERTIFIED
    assert derive_winners(races[0]).outcome == "skipped_measure"


@pytest.mark.django_db
def test_nc_ingest_matches_repaired_candidate_by_normalized_name():
    e = election()
    result = AdapterResult(
        _aggregate_rows([raw(title="STATE SENATE DISTRICT 01", choice="T. Lee Horne, III")]),
        "https://example.org/nc.zip",
        "full",
    )
    race = Race.objects.create(
        election=e,
        race_type=Race.RaceType.CANDIDATE,
        office_title="STATE SENATE DISTRICT 01",
        jurisdiction="NC",
        geography_scope="district",
        source=Race.Source.NC_SBE,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source_metadata={"nc_contest_key": result.rows[0].raw["nc_contest_key"]},
    )
    candidate = Candidate.objects.create(race=race, name="T. Lee Horne III")
    corrected = AdapterResult(
        _aggregate_rows([raw(title="STATE SENATE DISTRICT 01", choice="T. Lee Horne III", votes=11)]),
        "https://example.org/nc.zip",
        "full",
    )

    _process_race_results(race, result, "NC")
    first = OfficialResult.objects.get(race=race)
    _process_race_results(race, corrected, "NC")

    saved = OfficialResult.objects.get(race=race)
    assert saved.candidate_id == candidate.pk
    assert saved.pk == first.pk
    assert saved.vote_count == 11
    candidate.refresh_from_db()
    assert candidate.party == "DEM"
    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED


@pytest.mark.django_db
@pytest.mark.parametrize("seats", [("0", "0"), ("1", ""), ("1", "2")])
def test_missing_zero_and_conflicting_seats_are_not_proven(seats):
    e = election()
    result = AdapterResult(_aggregate_rows([raw(seats=seats[0]), raw(choice="Bob", seats=seats[1])]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    assert "source_vote_for" not in race.source_metadata
    assert "source_vote_for_unresolved" in race.source_metadata


@pytest.mark.django_db
def test_identity_mismatch_cannot_fall_back_to_title():
    e = election()
    result = AdapterResult(_aggregate_rows([raw(county="ORANGE")]), "", "full")
    race = Race.objects.create(
        election=e,
        race_type="candidate",
        office_title="SHERIFF",
        jurisdiction="NC",
        geography_scope="countywide",
        source="results_adapter",
        source_metadata={"nc_contest_key": "nc:v1:unrelated"},
    )
    Candidate.objects.create(race=race, name="Alice")
    _process_race_results(race, result, "NC")
    assert not race.official_results.exists()


@pytest.mark.django_db
def test_ordinary_ingest_cannot_repopulate_a_merged_legacy_race():
    e = election()
    race = Race.objects.create(
        election=e,
        race_type="candidate",
        office_title="SHERIFF",
        jurisdiction="NC",
        geography_scope="countywide",
        source="results_adapter",
    )
    Candidate.objects.create(race=race, name="Alice")
    result = AdapterResult(_aggregate_rows([raw(), raw(county="ORANGE")]), "", "full")
    _process_race_results(race, result, "NC")
    assert not race.official_results.exists()


@pytest.mark.django_db
def test_verified_county_with_sourced_seats_can_derive_winners():
    from results.winners import derive_winners

    e = election()
    result = AdapterResult(_aggregate_rows([raw(), raw(choice="Bob", votes=4)]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    _process_race_results(race, result, "NC")
    race.refresh_from_db()
    assert derive_winners(race).outcome == "derived"


@pytest.mark.django_db
def test_unresolved_nc_seats_remain_ineligible():
    from results.winners import derive_winners

    e = election()
    result = AdapterResult(_aggregate_rows([raw(kind="S", title="NC GOVERNOR", seats="0")]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    _process_race_results(race, result, "NC")
    race.refresh_from_db()
    assert derive_winners(race).outcome == "skipped_unknown_seats"


@pytest.mark.django_db
def test_results_bootstrap_and_filing_ingest_share_canonical_key():
    from aggregation.ingest import ingest_race
    from integrations.nc_sbe.mappers import map_race_identity

    e = election()
    result = AdapterResult(_aggregate_rows([raw(kind="S", title="NC GOVERNOR")]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    identity, fields = map_race_identity("GOVERNOR", "", True, 1, "4")
    filing, created = ingest_race(election=e, source="nc_sbe", identity=identity, fields=fields)
    assert created is False
    assert filing.pk == race.pk


@pytest.mark.django_db
def test_filing_first_gets_nc_identity_before_first_results_ingest():
    from aggregation.ingest import ingest_race
    from integrations.nc_sbe.mappers import map_race_identity

    e = election()
    identity, fields = map_race_identity("GOVERNOR", "", True, 1, "4")
    race, _ = ingest_race(election=e, source="nc_sbe", identity=identity, fields=fields)
    Candidate.objects.create(race=race, name="Alice")
    result = AdapterResult(_aggregate_rows([raw(kind="S", title="NC GOVERNOR")]), "", "full")
    _process_race_results(race, result, "NC")
    race.refresh_from_db()
    assert race.official_results.get().vote_count == 10
    assert race.source_metadata["nc_contest_key"] == result.rows[0].raw["nc_contest_key"]


@pytest.mark.django_db
@pytest.mark.parametrize("flag", [True, False])
def test_corrected_nc_ingest_preserves_source_outcome(flag):
    e = election()
    result = AdapterResult(_aggregate_rows([raw()]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    _process_race_results(race, result, "NC")
    race.official_results.update(is_winner=flag)
    result.rows[0].vote_count = 11
    _process_race_results(race, result, "NC")
    row = race.official_results.get()
    assert row.is_winner is flag
    assert row.vote_count == 11


def test_write_in_choices_share_one_natural_key_and_preserve_components():
    rows = _aggregate_rows(
        [raw(choice="Write-In (Miscellaneous)", votes=4), raw(choice="Write-In (Jane Doe)", votes=6)]
    )
    assert len(rows) == 1
    assert rows[0].is_write_in_aggregate
    assert rows[0].vote_count == 10
    assert rows[0].raw["write_in_components"] == {"Write-In (Miscellaneous)": 4, "Write-In (Jane Doe)": 6}


@pytest.mark.django_db
def test_filing_sync_preserves_results_identity_and_sourced_seats(monkeypatch):
    from unittest.mock import MagicMock

    from integrations.nc_sbe.tasks import sync_nc_candidates
    from integrations.nc_sbe.tests.test_tasks import _candidate_row, _csv_bytes

    e = election()
    result = AdapterResult(_aggregate_rows([raw(kind="S", title="NC STATE SENATE DISTRICT 01", seats="2")]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    key = race.source_metadata["nc_contest_key"]
    client = MagicMock()
    client.list_candidate_filing_csv_key.return_value = "filings.csv"
    client.fetch_candidate_filing_csv.return_value = _csv_bytes(
        _candidate_row("11/05/2024", "ALAMANCE", "NC STATE SENATE DISTRICT 01", "Alice", "", "DEM")
    )
    monkeypatch.setattr("integrations.nc_sbe.tasks.NcSbeClient", lambda: client)
    sync_nc_candidates.apply(throw=True)
    race.refresh_from_db()
    assert Race.objects.filter(election=e).count() == 1
    assert race.source_metadata["nc_contest_key"] == key
    assert race.max_selections == 2


@pytest.mark.django_db
def test_unknown_multicounty_local_contests_are_not_bootstrapped_as_two_races():
    e = election()
    result = AdapterResult(
        _aggregate_rows(
            [raw(title="CITY OF SPRINGFIELD MAYOR"), raw(title="CITY OF SPRINGFIELD MAYOR", county="ORANGE")]
        ),
        "",
        "full",
    )
    assert _bootstrap_races_from_results(e, result, "NC") == []
    assert not e.races.exists()


@pytest.mark.django_db
def test_invalid_source_count_cannot_replace_a_good_total():
    e = election()
    result = AdapterResult(_aggregate_rows([raw()]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    _process_race_results(race, result, "NC")
    malformed = AdapterResult(_aggregate_rows([raw(votes="not-a-number")]), "", "full")
    _process_race_results(race, malformed, "NC")
    assert race.official_results.get().vote_count == 10


@pytest.mark.django_db
def test_flagged_nc_election_classification_remains_ineligible():
    from results.winners import derive_winners

    e = election()
    e.needs_review = True
    e.save()
    result = AdapterResult(_aggregate_rows([raw()]), "", "full")
    race = _bootstrap_races_from_results(e, result, "NC")[0]
    _process_race_results(race, result, "NC")
    race.refresh_from_db()
    assert derive_winners(race).outcome == "skipped_election_classification"


def test_different_local_source_ids_do_not_prove_different_electorates():
    rows = _aggregate_rows(
        [
            raw(title="TOWN OF MOUNT OLIVE MAYOR", code="1", county="DUPLIN"),
            raw(title="TOWN OF MOUNT OLIVE MAYOR", code="2", county="WAYNE"),
        ]
    )
    assert all(row.raw["nc_identity_verified"] is False for row in rows)
