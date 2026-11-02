from datetime import date

import pytest

from aggregation.identity import election_canonical_key, race_canonical_key
from elections.models import Candidate, Election, Race
from results.adapters.nc import _aggregate_rows
from results.models import OfficialResult
from results.tests.test_nc_identity import raw


@pytest.fixture
def mixed(db):
    election = Election.objects.create(
        name="NC 2024",
        state="NC",
        election_date=date(2024, 11, 5),
        election_type="general",
        jurisdiction_level="state",
        canonical_key="NC:general:2024-11-05:state",
    )
    races = []
    inputs = [
        ("NC GOVERNOR", "WAKE", "S", "1"),
        ("SHERIFF", "WAKE", "C", "2"),
        ("CITY OF ASHEVILLE MAYOR", "BUNCOMBE", "C", "3"),
    ]
    rows = _aggregate_rows([raw(title=t, county=c, kind=k, code=code) for t, c, k, code in inputs])
    for t, c, k, code in inputs:
        race = Race.objects.create(
            election=election,
            office_title=t,
            race_type="candidate",
            source="results_adapter",
            canonical_key=race_canonical_key(election.canonical_key, t, "", "candidate"),
        )
        candidate = Candidate.objects.create(race=race, name="Alice", party="DEM")
        OfficialResult.objects.create(race=race, candidate=candidate, vote_count=10, result_type="official")
        races.append(race)
    return election, races, rows


@pytest.mark.django_db
def test_mixed_repair_is_no_write_by_default_then_preserves_ids_and_result_values(mixed):
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan

    election, races, rows = mixed
    before = list(OfficialResult.objects.order_by("pk").values_list("pk", "race_id", "candidate_id", "vote_count"))
    report = build_classification_plan(election, [], rows, {"results": "source"})
    assert not report["held"]
    assert len(report["targets"]) == 3
    assert Election.objects.count() == 1
    assert list(Race.objects.values_list("election_id", flat=True)) == [election.pk] * 3
    apply_classification_plan(election, [], rows, {"results": "source"}, report)
    assert Election.objects.count() == 3
    assert before == list(
        OfficialResult.objects.order_by("pk").values_list("pk", "race_id", "candidate_id", "vote_count")
    )
    for race in races:
        race.refresh_from_db()
        assert race.source_metadata["nc_classification"]["evidence_status"] in {"confirmed", "inferred"}
        assert race.canonical_key.startswith(race.election.canonical_key + "|")
    assert len({r.election_id for r in races}) == 3


@pytest.mark.django_db
def test_repair_rejects_stale_source_or_database_and_keeps_everything_unchanged(mixed):
    from integrations.nc_sbe.election_repair import (
        ClassificationConflict,
        apply_classification_plan,
        build_classification_plan,
    )

    election, races, rows = mixed
    report = build_classification_plan(election, [], rows, {"results": "source"})
    with pytest.raises(ClassificationConflict, match="fingerprint"):
        apply_classification_plan(election, [], rows, {"results": "different"}, report)
    Candidate.objects.filter(race=races[0]).update(incumbent=True)
    with pytest.raises(ClassificationConflict, match="fingerprint"):
        apply_classification_plan(election, [], rows, {"results": "source"}, report)
    assert Election.objects.count() == 1
    assert set(Race.objects.values_list("election_id", flat=True)) == {election.pk}


@pytest.mark.django_db
def test_repair_repeat_converges_and_source_record_relationships_survive(mixed):
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan
    from ops.models import SourceRecord

    election, races, rows = mixed
    record = SourceRecord.objects.create(
        source="civic",
        external_id="record",
        raw_payload={},
        payload_checksum="x",
        linked_race=races[1],
        linked_candidate=races[1].candidates.get(),
    )
    report = build_classification_plan(election, [], rows, {"results": "source"})
    apply_classification_plan(election, [], rows, {"results": "source"}, report)
    snapshot = list(Race.objects.order_by("pk").values_list("pk", "election_id", "canonical_key"))
    report = build_classification_plan(election, [], rows, {"results": "source"})
    apply_classification_plan(election, [], rows, {"results": "source"}, report)
    assert snapshot == list(Race.objects.order_by("pk").values_list("pk", "election_id", "canonical_key"))
    record.refresh_from_db()
    assert record.linked_race_id == races[1].pk
    assert record.linked_candidate_id == races[1].candidates.get().pk


@pytest.mark.django_db
def test_external_destination_changes_require_fresh_approval(mixed):
    from integrations.nc_sbe.classification import classify_nc_contest
    from integrations.nc_sbe.election_repair import (
        ClassificationConflict,
        apply_classification_plan,
        build_classification_plan,
    )
    from integrations.nc_sbe.event_identity import ensure_event

    election, _, rows = mixed
    target, _ = ensure_event(election.election_date, classify_nc_contest(election.election_date, 'SHERIFF', county='WAKE'))
    report = build_classification_plan(election, [], rows, {'results':'source'})
    target.source_metadata['review_note'] = 'changed since approval'
    target.save()
    with pytest.raises(ClassificationConflict, match='fingerprint'):
        apply_classification_plan(election, [], rows, {'results':'source'}, report)


@pytest.mark.django_db
def test_external_held_destination_is_not_unheld_by_repair(mixed):
    from integrations.nc_sbe.classification import classify_nc_contest
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan
    from integrations.nc_sbe.event_identity import ensure_event

    election, races, rows = mixed
    target, _ = ensure_event(election.election_date, classify_nc_contest(election.election_date, 'SHERIFF', county='WAKE'))
    target.source_metadata['nc_classification_container'] = True
    target.save()
    before = target.source_metadata.copy()
    report = build_classification_plan(election, [], rows, {'results':'source'})
    assert {'race_id': races[1].pk, 'reason': 'target_event_held'} in report['held']
    apply_classification_plan(election, [], rows, {'results':'source'}, report)
    target.refresh_from_db()
    assert target.source_metadata == before


@pytest.mark.django_db
def test_reviewed_future_zero_archive_resets_false_certification_without_changing_votes(mixed):
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan

    election, races, rows = mixed
    election.election_date = date(2098, 11, 4)
    election.status = 'results_certified'
    election.save()
    Race.objects.filter(election=election).update(certification_status='results_certified', race_status='archived')
    OfficialResult.objects.filter(race__election=election).update(vote_count=0)
    for row in rows:
        row.vote_count = 0
    report = build_classification_plan(election, [], rows, {'results':'source'})
    assert report['pre_election_resets']['race_ids'] == [r.pk for r in races]
    before = list(OfficialResult.objects.order_by('pk').values_list('pk', 'race_id', 'candidate_id', 'vote_count'))
    apply_classification_plan(election, [], rows, {'results':'source'}, report)
    assert before == list(OfficialResult.objects.order_by('pk').values_list('pk', 'race_id', 'candidate_id', 'vote_count'))
    for race in races:
        race.refresh_from_db()
        assert race.certification_status == 'upcoming'
        assert race.race_status == 'active'
        assert race.election.status == 'upcoming'
    assert set(OfficialResult.objects.values_list('result_type', flat=True)) == {'unofficial'}


@pytest.mark.django_db
def test_existing_source_mismatch_and_unresolved_electorate_are_held_without_race_changes(mixed):
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan

    election, races, rows = mixed
    OfficialResult.objects.filter(race=races[1]).update(vote_count=999)
    rows[-1].raw["nc_identity_verified"] = False
    snapshot = list(Race.objects.filter(pk__in=[races[1].pk, races[2].pk]).order_by("pk").values())
    report = build_classification_plan(election, [], rows, {"results": "source"})
    assert {h["race_id"] for h in report["held"]} == {races[1].pk, races[2].pk}
    apply_classification_plan(election, [], rows, {"results": "source"}, report)
    assert snapshot == list(Race.objects.filter(pk__in=[races[1].pk, races[2].pk]).order_by("pk").values())


@pytest.mark.django_db
def test_secondary_nc_source_cannot_recreate_old_date_bucket():
    from aggregation.ingest import ingest_election
    from integrations.nc_sbe.classification import classify_nc_contest
    from integrations.nc_sbe.event_identity import ensure_event

    day = date(2019, 7, 9)
    event, _ = ensure_event(day, classify_nc_contest(day, "US HOUSE OF REPRESENTATIVES DISTRICT 03 (REP)"))
    with pytest.raises(ValueError, match="NC.*scope"):
        ingest_election(
            source="civic_api",
            source_id="new-source",
            identity={"state": "NC", "election_date": day, "election_type": "special", "jurisdiction_level": "state"},
            fields={},
        )
    assert Election.objects.count() == 1
    assert not Election.objects.filter(canonical_key=election_canonical_key("NC", "special", day, "state")).exists()
    assert Election.objects.get().pk == event.pk


@pytest.mark.django_db
def test_api_exposes_inferred_classification_and_legacy_parent_replacements(mixed):
    from api.serializers import ElectionSerializer, RaceDetailSerializer
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan

    election, races, rows = mixed
    report = build_classification_plan(election, [], rows, {"results": "source"})
    apply_classification_plan(election, [], rows, {"results": "source"}, report)
    municipal = Race.objects.get(pk=races[-1].pk)
    assert RaceDetailSerializer(municipal).data["classification"]["phase"] == "general"
    payload = ElectionSerializer(municipal.election).data
    assert payload["classification"]["evidence_status"] == "inferred"
    assert payload["needs_review"] is False


@pytest.mark.django_db
def test_report_write_failure_rolls_back_all_reparenting(mixed):
    from integrations.nc_sbe.election_repair import apply_classification_plan, build_classification_plan

    election, races, rows = mixed
    report = build_classification_plan(election, [], rows, {"results": "source"})

    def fail(_):
        raise OSError("report storage failed")

    with pytest.raises(OSError, match="report storage"):
        apply_classification_plan(election, [], rows, {"results": "source"}, report, write_report=fail)
    assert Election.objects.count() == 1
    assert set(Race.objects.values_list("election_id", flat=True)) == {election.pk}


@pytest.mark.django_db
def test_cli_preview_then_reviewed_apply_for_known_special_second_primary(tmp_path):
    import io
    import json
    import zipfile

    from django.core.management import call_command

    election = Election.objects.create(
        name="2019 special",
        state="NC",
        election_date=date(2019, 7, 9),
        election_type="special",
        jurisdiction_level="state",
        canonical_key="NC:special:2019-07-09:state",
    )
    title = "US HOUSE OF REPRESENTATIVES DISTRICT 03 (REP)"
    Race.objects.create(election=election, office_title=title, race_type="candidate", source="results_adapter")
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "results.txt",
            "County\tElection Date\tContest Group ID\tContest Type\tContest Name\tChoice\tChoice Party\tVote For\tTotal Votes\n"
            f"BEAUFORT\t07/09/2019\t1\tS\t{title}\tAlice\tREP\t1\t10\n",
        )
    source = tmp_path / "results.zip"
    source.write_bytes(payload.getvalue())
    filings = tmp_path / "filings.csv"
    filings.write_text(
        "election_dt,county_name,contest_name,party_contest,is_unexpired\n"
        "07/09/2019,BEAUFORT,US HOUSE OF REPRESENTATIVES DISTRICT 03,REP,TRUE\n"
    )
    preview = tmp_path / "preview.json"
    common = dict(election_id=election.pk, source_file=str(source), filing_file=str(filings), stdout=io.StringIO())
    call_command("repair_nc_election_classification", report=str(preview), **common)
    assert json.loads(preview.read_text())["dry_run"] is True
    election.refresh_from_db()
    assert election.election_type == "special"
    call_command(
        "repair_nc_election_classification",
        report=str(tmp_path / "applied.json"),
        apply=True,
        approved_report=str(preview),
        **common,
    )
    election.refresh_from_db()
    assert election.election_type == "primary_runoff"
    assert Election.objects.count() == 1


@pytest.mark.django_db
def test_target_key_collision_holds_the_component_but_keeps_other_preview_mappings(mixed):
    from integrations.nc_sbe.classification import classify_nc_contest
    from integrations.nc_sbe.election_repair import build_classification_plan
    from integrations.nc_sbe.event_identity import event_key

    election, races, rows = mixed
    target = event_key(election.election_date, classify_nc_contest(election.election_date, "SHERIFF", county="WAKE"))
    collision = Race.objects.create(
        election=election,
        office_title="SHERIFF",
        race_type="candidate",
        source="nc_sbe",
        canonical_key=race_canonical_key(target, "SHERIFF", "", "candidate"),
    )
    report = build_classification_plan(election, [], rows, {"results": "source"})
    held = {x["race_id"] for x in report["held"]}
    assert races[1].pk in held and collision.pk in held
    assert races[0].pk in {x["race_id"] for x in report["moves"]}
