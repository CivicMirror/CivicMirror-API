"""Source-specific party capture and metadata-only backfill regression tests."""
import json
from io import StringIO

import pytest
from django.core.management import call_command

from elections.models import Candidate, Election, Race
from results.adapters.base import AdapterResult, ResultRow
from results.models import OfficialResult
from results.tasks import _bootstrap_races_from_results


def election(state):
    return Election.objects.create(name="Primary", election_date="2026-05-19", election_type="primary", state=state)


def row(name="A", title="Governor", raw=None, votes=10, fragment=""):
    return ResultRow(name, None, votes, None, None, "official", office_title=title,
                     raw=raw or {}, jurisdiction_fragment=fragment)


@pytest.mark.django_db
@pytest.mark.parametrize("state,title,raw,expected_race", [
    ("CT", "Governor", {"contest_code": "1", "party_code": "Democratic"}, "DEM"),
    ("GA", "Governor - Dem", {"party": "D"}, "DEM"),
    ("GA", "Governor - Dem", {}, "DEM"),
    ("PA", "Governor", {"party": "Democratic"}, ""),
    ("MO", "Governor", {"party": "Dem"}, ""),
])
def test_bootstrap_source_party_capture(state, title, raw, expected_race):
    target = election(state)
    if state == "MO":
        target.election_date = "2024-11-05"
        target.election_type = "general"
        target.save(update_fields=["election_date", "election_type"])
    races = _bootstrap_races_from_results(target, AdapterResult([row(title=title, raw=raw)], "", "full"), state)
    race = races[0]
    race.refresh_from_db()
    candidate = race.candidates.get()
    assert (race.party, race.normalized_party) == (expected_race, expected_race)
    assert (candidate.party, candidate.normalized_party) == ("DEM", "DEM")
    assert "party" in candidate.field_provenance


@pytest.mark.django_db
def test_ct_bootstrap_preserves_distinct_party_identities():
    rows = [row(raw={"contest_code": "1", "party_code": party}) for party in ("Democratic", "Republican")]
    races = _bootstrap_races_from_results(election("CT"), AdapterResult(rows, "", "full"), "CT")
    assert sorted(r.party for r in Race.objects.filter(pk__in=[r.pk for r in races])) == ["DEM", "REP"]
    assert {r.source_metadata["party_code"] for r in races} == {"Democratic", "Republican"}


@pytest.mark.django_db
def test_ga_suffix_conflict_is_reported_and_cannot_enable_nomination():
    from results.winners import derive_winners

    races = _bootstrap_races_from_results(election("GA"), AdapterResult([
        row(title="Governor - Dem", raw={"party": "REP"})], "", "full"), "GA")
    race = Race.objects.get(pk=races[0].pk)
    candidate = race.candidates.get()
    assert candidate.party == ""
    assert race.source_metadata["results_party_unresolved"]
    race.certification_status = "results_certified"
    OfficialResult.objects.create(race=race, candidate=candidate, vote_count=10, result_type="official")
    assert derive_winners(race).outcome == "skipped_primary_unpartitioned"


@pytest.mark.django_db
def test_pa_backfill_uses_county_evidence_without_changing_votes_or_source_flags():
    race = Race.objects.create(election=election("PA"), office_title="Governor", source="results_adapter", race_type="candidate")
    candidate = Candidate.objects.create(race=race, name="A")
    total = OfficialResult.objects.create(race=race, candidate=candidate, vote_count=30, is_winner=True)
    for county, votes, party in [("ADAMS", 10, "Dem"), ("YORK", 20, "Democratic")]:
        OfficialResult.objects.create(race=race, candidate=candidate, vote_count=votes,
                                      jurisdiction_fragment=county, raw_payload={"party": party})
    original_rows = list(race.official_results.values())
    output = StringIO()
    call_command("backfill_result_parties", state="PA", stdout=output)
    plan = json.loads(output.getvalue())
    assert plan["dry_run"] is True
    assert plan["races"][0]["changes"]
    candidate.refresh_from_db()
    assert candidate.party == ""
    call_command("backfill_result_parties", state="PA", apply=True, stdout=StringIO())
    candidate.refresh_from_db()
    assert (candidate.party, candidate.normalized_party) == ("DEM", "DEM")
    assert list(race.official_results.values()) == original_rows
    total.refresh_from_db()
    assert total.is_winner is True
    output = StringIO()
    call_command("backfill_result_parties", state="PA", apply=True, stdout=output)
    assert json.loads(output.getvalue())["races"][0]["changes"] == []


@pytest.mark.django_db
@pytest.mark.parametrize("existing,county_parties,reason", [
    ("Republican", ["Democratic"], "conflicting_party"),
    ("", ["Democratic", "Republican"], "conflicting_party"),
    ("", ["", ""], "missing_party"),
])
def test_backfill_preserves_existing_party_and_reports_unresolved(existing, county_parties, reason):
    race = Race.objects.create(election=election("PA"), office_title="Governor", source="results_adapter", race_type="candidate")
    candidate = Candidate.objects.create(race=race, name="A", party=existing,
                                         field_provenance={"party": "authoritative_source"})
    for index, party in enumerate(county_parties):
        OfficialResult.objects.create(race=race, candidate=candidate, vote_count=10,
                                      jurisdiction_fragment=str(index), raw_payload={"party": party})
    output = StringIO()
    call_command("backfill_result_parties", apply=True, stdout=output)
    plan = json.loads(output.getvalue())["races"][0]
    assert plan["unresolved"][0]["reason"] == reason
    candidate.refresh_from_db()
    assert candidate.party == existing
    assert candidate.field_provenance["party"] == "authoritative_source"


@pytest.mark.django_db
def test_mo_historical_general_payload_cannot_supply_primary_party_backfill():
    race = Race.objects.create(election=election("MO"), office_title="Governor", source="results_adapter", race_type="candidate")
    candidate = Candidate.objects.create(race=race, name="A")
    OfficialResult.objects.create(race=race, candidate=candidate, vote_count=10, raw_payload={"party": "REP"},
                                  source_url="https://www.sos.mo.gov/CMSImages/2024GeneralElection.pdf")
    output = StringIO()
    call_command("backfill_result_parties", apply=True, stdout=output)
    assert json.loads(output.getvalue())["races"][0]["unresolved"][0]["reason"] == "source_election_mismatch"
    candidate.refresh_from_db()
    assert candidate.party == ""


@pytest.mark.django_db
def test_mo_adapter_refuses_dates_outside_its_historical_general_source(monkeypatch):
    from results.adapters.mo import MissouriAdapter

    def unexpected_fetch(*args):
        pytest.fail("A mismatched election must be rejected before fetching the historical PDF")

    monkeypatch.setattr(MissouriAdapter, "_fetch_grand_totals_pdf_bytes", unexpected_fetch)
    target = election("MO")
    result = MissouriAdapter().fetch_results(target.election_date, target.pk)
    assert result.rows == []
    assert result.mapping_confidence == "none"


@pytest.mark.django_db
def test_corrected_party_evidence_is_reconciled_before_ingest_derivation(settings):
    from results.tasks import _process_race_results

    settings.DERIVE_WINNERS_ENABLED = True
    first = AdapterResult([row(title="Governor - Dem", raw={"party": "DEM"})], "", "full")
    race = _bootstrap_races_from_results(election("GA"), first, "GA")[0]
    _process_race_results(race, first, "GA")
    assert race.official_results.get().is_winner is True
    correction = AdapterResult([row(title="Governor - Dem", raw={"party": "REP"})], "", "full")
    _process_race_results(race, correction, "GA")
    race.refresh_from_db()
    assert race.source_metadata["results_party_unresolved"]
    assert race.official_results.get().is_winner is None
    correction.rows[0].is_winner = False
    _process_race_results(race, correction, "GA")
    assert race.official_results.get().is_winner is False


@pytest.mark.django_db
def test_new_party_evidence_resolves_missing_marker_during_ingestion(settings):
    from results.tasks import _process_race_results

    settings.DERIVE_WINNERS_ENABLED = True
    first = AdapterResult([row()], "", "full")
    race = _bootstrap_races_from_results(election("PA"), first, "PA")[0]
    assert race.source_metadata["results_party_unresolved"]
    correction = AdapterResult([row(raw={"party": "DEM"})], "", "full")
    _process_race_results(race, correction, "PA")
    race.refresh_from_db()
    assert "results_party_unresolved" not in race.source_metadata
    assert race.candidates.get().party == "DEM"
    assert race.official_results.get().is_winner is True
