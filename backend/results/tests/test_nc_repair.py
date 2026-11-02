from datetime import date

import pytest
from django.db.models import Sum
from django.test import Client

from community.models import MockVote
from elections.models import Candidate, Election, Race
from ops.models import SourceRecord
from results.adapters.base import AdapterResult
from results.adapters.nc import _aggregate_rows
from results.models import OfficialResult

from .test_nc_identity import raw


def setup_race(e, title="NC STATE SENATE DISTRICT 01", source="results_adapter", **kwargs):
    return Race.objects.create(
        election=e,
        office_title=title,
        race_type="candidate",
        source=source,
        geography_scope="district",
        jurisdiction="NC",
        **kwargs,
    )


@pytest.fixture
def e(db):
    return Election.objects.create(
        name="NC 2024", election_date=date(2024, 11, 5), election_type="general", state="NC", jurisdiction_level="state"
    )


@pytest.fixture
def duplicate(e):
    legacy = setup_race(e, source_metadata={"winners_derived": True})
    filing = setup_race(
        e,
        source="nc_sbe",
        canonical_key="filing-key",
        source_metadata={"contest_variant": "nc:NC STATE SENATE DISTRICT 01:general"},
    )
    a = Candidate.objects.create(race=legacy, name="Alice")
    b = Candidate.objects.create(
        race=filing,
        name="Alice",
        party="REP",
        incumbent=True,
        field_provenance={"party": "nc_sbe", "incumbent": "nc_sbe"},
    )
    OfficialResult.objects.create(race=legacy, candidate=a, vote_count=10, result_type="official", is_winner=True)
    result = AdapterResult(
        _aggregate_rows([raw(kind="S", title=legacy.office_title, party="REP")]),
        "https://example.org/results.zip",
        "full",
        source_version="source-hash",
    )
    return legacy, filing, a, b, result


def repair(e, result, apply=False):
    from results.nc_repair import apply_repair_plan, build_repair_plan

    report = build_repair_plan(e, result)
    if apply:
        apply_repair_plan(e, result, report["fingerprint"])
    return report


@pytest.mark.django_db
def test_dry_run_maps_duplicates_and_preserves_database(e, duplicate):
    legacy, filing, a, b, result = duplicate
    report = repair(e, result)
    assert not report["conflicts"]
    assert report["race_mapping"][str(legacy.pk)] == [result.rows[0].raw["nc_contest_key"]]
    assert report["groups"][0]["canonical_race_id"] == filing.pk
    assert report["vote_reconciliation"][0]["matched"] is True
    assert Race.objects.count() == 2
    assert OfficialResult.objects.get().candidate_id == a.pk
    assert not filing.source_metadata.get("nc_contest_key")


@pytest.mark.django_db
def test_merge_preserves_incumbency_results_and_relationships(e, duplicate):
    from results.nc_repair import build_repair_plan

    legacy, filing, a, b, result = duplicate
    vote = MockVote.objects.create(uid="voter", race=legacy, candidate_ids=[a.pk], ranked_selections=[a.pk])
    record = SourceRecord.objects.create(
        source="civic",
        external_id="candidate",
        raw_payload={},
        payload_checksum="abc",
        linked_race=legacy,
        linked_candidate=a,
    )
    repair(e, result, apply=True)
    filing.refresh_from_db()
    legacy.refresh_from_db()
    record.refresh_from_db()
    vote.refresh_from_db()
    assert filing.certification_status == "results_certified"
    assert filing.canonical_key == "filing-key"
    assert filing.candidates.get().incumbent is True
    assert filing.candidates.get().party == "REP"
    assert filing.official_results.get().vote_count == 10
    assert not legacy.official_results.exists()
    assert legacy.source_metadata["nc_superseded_by"] == [filing.pk]
    assert record.linked_race_id == filing.pk and record.linked_candidate_id == b.pk
    assert vote.race_id == filing.pk and vote.candidate_ids == [b.pk] and vote.ranked_selections == [b.pk]
    assert not build_repair_plan(e, result)["conflicts"]
    before = list(OfficialResult.objects.values())
    repair(e, result, apply=True)
    assert list(OfficialResult.objects.values()) == before


@pytest.mark.django_db
def test_split_reconciles_merged_votes_per_choice(e):
    legacy = setup_race(e, title="SHERIFF")
    a = Candidate.objects.create(race=legacy, name="Alice")
    OfficialResult.objects.create(race=legacy, candidate=a, vote_count=40, result_type="official")
    result = AdapterResult(_aggregate_rows([raw(), raw(county="ORANGE", votes=30)]), "", "full")
    report = repair(e, result, apply=True)
    assert not report["conflicts"]
    assert len(report["race_mapping"][str(legacy.pk)]) == 2
    assert sorted(OfficialResult.objects.values_list("vote_count", flat=True)) == [10, 30]
    assert OfficialResult.objects.aggregate(total=Sum("vote_count"))["total"] == 40


@pytest.mark.django_db
def test_vote_mismatch_blocks_apply(e, duplicate):
    from results.nc_repair import RepairConflict

    _, _, _, _, result = duplicate
    result.rows[0].vote_count = 20
    report = repair(e, result)
    assert any(c["reason"] == "vote_mismatch" for c in report["conflicts"])
    with pytest.raises(RepairConflict):
        repair(e, result, apply=True)
    assert OfficialResult.objects.get().vote_count == 10


@pytest.mark.django_db
def test_stale_report_is_rejected(e, duplicate):
    from results.nc_repair import RepairConflict, apply_repair_plan

    _, _, a, _, result = duplicate
    report = repair(e, result)
    a.website_url = "https://new.example.org"
    a.save()
    with pytest.raises(RepairConflict, match="changed"):
        apply_repair_plan(e, result, report["fingerprint"])


@pytest.mark.django_db
def test_source_winner_true_and_false_survive_merge(e, duplicate):
    legacy, filing, a, b, result = duplicate
    legacy.source_metadata = {}
    legacy.save()
    repair(e, result, apply=True)
    assert filing.official_results.get().is_winner is True


@pytest.mark.django_db
def test_conflicting_candidate_party_blocks_merge(e, duplicate):
    _, _, _, b, result = duplicate
    b.party = "DEM"
    b.save()
    report = repair(e, result)
    assert any(c["reason"] == "candidate_party_conflict" for c in report["conflicts"])


@pytest.mark.django_db(transaction=True)
def test_apply_rolls_back_every_write(e, duplicate, monkeypatch):
    import results.nc_repair as module

    _, _, _, _, result = duplicate
    report = repair(e, result)
    before = list(Race.objects.values())

    def fail(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(module, "_store_race_results", fail)
    with pytest.raises(RuntimeError, match="forced failure"):
        module.apply_repair_plan(e, result, report["fingerprint"])
    assert list(Race.objects.values()) == before
    assert OfficialResult.objects.count() == 1


@pytest.mark.django_db
def test_api_returns_one_combined_race_and_candidate(e, duplicate, make_api_key):
    legacy, filing, a, b, result = duplicate
    make_api_key("test-key")
    repair(e, result, apply=True)
    client = Client(HTTP_X_API_KEY="test-key")
    payload = client.get("/api/races/", {"election": e.pk}).json()
    assert payload["count"] == 1
    races = client.get(f"/api/elections/{e.pk}/races/").json()
    assert races["count"] == 1
    detail = client.get(f"/api/races/{filing.pk}/").json()
    assert detail["certification_status"] == "results_certified"
    assert detail["candidates"][0]["party"] == "REP"
    assert detail["candidates"][0]["incumbent"] is True
    assert client.get(f"/api/races/{legacy.pk}/results/").status_code == 404


@pytest.mark.django_db
def test_scoped_repair_expands_duplicate_pair_and_holds_unrelated_conflicts(e, duplicate):
    from results.nc_repair import apply_repair_plan, build_repair_plan

    legacy, filing, a, b, result = duplicate
    other = setup_race(e, title="UNKNOWN LOCAL CONTEST")
    report = build_repair_plan(e, result, race_ids=[legacy.pk])
    assert not report["conflicts"]
    assert set(report["race_mapping"]) == {str(legacy.pk), str(filing.pk)}
    apply_repair_plan(e, result, report["fingerprint"], race_ids=[legacy.pk])
    other.refresh_from_db()
    assert "nc_superseded_by" not in other.source_metadata


@pytest.mark.django_db
def test_unidentified_write_in_overwrite_is_reported_as_reaggregation(e):
    legacy = setup_race(e, title="SHERIFF")
    OfficialResult.objects.create(
        race=legacy, vote_count=6, result_type="official", is_write_in_aggregate=True, raw_payload={"source": "nc_sbe"}
    )
    result = AdapterResult(
        _aggregate_rows([raw(choice="Write-In (Miscellaneous)", votes=4), raw(choice="Write-In (Jane Doe)", votes=6)]),
        "",
        "full",
    )
    report = repair(e, result, apply=True)
    assert report["vote_reconciliation"][0]["correction"] == "write_in_reaggregation"
    assert OfficialResult.objects.get().vote_count == 10


@pytest.mark.django_db
def test_measure_misclassified_as_candidate_is_repaired_without_losing_audit(e):
    legacy = setup_race(e, title="COUNTY SALES TAX")
    for name, votes in [("FOR", 5), ("AGAINST", 3)]:
        candidate = Candidate.objects.create(race=legacy, name=name)
        OfficialResult.objects.create(race=legacy, candidate=candidate, vote_count=votes, result_type="official")
    result = AdapterResult(
        _aggregate_rows(
            [
                raw(title="COUNTY SALES TAX", choice="FOR", votes=5),
                raw(title="COUNTY SALES TAX", choice="AGAINST", votes=3),
            ]
        ),
        "",
        "full",
    )
    report = repair(e, result, apply=True)
    assert not report["conflicts"]
    assert OfficialResult.objects.count() == 2
    assert all(r.measure_option_id and not r.candidate_id for r in OfficialResult.objects.all())
    assert legacy.candidates.count() == 2


@pytest.mark.django_db
def test_command_dry_run_bypasses_adapter_cache_and_requires_review_before_apply(e, duplicate, tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock

    from django.core.management import call_command
    from django.core.management.base import CommandError

    legacy, filing, a, b, result = duplicate
    client = MagicMock()
    client.fetch_results_zip.return_value = b"fresh-source"
    monkeypatch.setattr("results.management.commands.repair_nc_contest_identity.NcSbeClient", lambda: client)
    monkeypatch.setattr(
        "results.management.commands.repair_nc_contest_identity.parse_results_tsv",
        lambda content: [raw(kind="S", title=legacy.office_title, party="REP")],
    )
    report_path = tmp_path / "review.json"
    call_command("repair_nc_contest_identity", election_id=e.pk, race_ids=[legacy.pk], report=str(report_path))
    report = json.loads(report_path.read_text())
    assert report["dry_run"] is True and report["applied"] is False
    assert report["source_version"]
    assert client.fetch_results_zip.call_count == 1
    assert not filing.source_metadata.get("nc_contest_key")
    with pytest.raises(CommandError, match="approved-report"):
        call_command("repair_nc_contest_identity", election_id=e.pk, report=str(tmp_path / "apply.json"), apply=True)
    call_command(
        "repair_nc_contest_identity",
        election_id=e.pk,
        race_ids=[legacy.pk],
        report=str(tmp_path / "applied.json"),
        apply=True,
        approved_report=str(report_path),
    )
    filing.refresh_from_db()
    assert filing.certification_status == "results_certified"
    assert json.loads((tmp_path / "applied.json").read_text())["applied"] is True


@pytest.mark.django_db
def test_command_rejects_wrong_election_source(e, tmp_path, monkeypatch):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    monkeypatch.setattr(
        "results.management.commands.repair_nc_contest_identity.parse_results_tsv",
        lambda content: [{**raw(), "Election Date": "03/05/2024"}],
    )
    source = tmp_path / "other.zip"
    source.write_bytes(b"wrong-election")
    with pytest.raises(CommandError, match="election date"):
        call_command(
            "repair_nc_contest_identity",
            election_id=e.pk,
            report=str(tmp_path / "report.json"),
            source_file=str(source),
        )


@pytest.mark.django_db
def test_scoped_repair_can_be_repeated_using_retired_race_id(e, duplicate):
    from results.nc_repair import apply_repair_plan, build_repair_plan

    legacy, filing, a, b, result = duplicate
    plan = build_repair_plan(e, result, race_ids=[legacy.pk])
    apply_repair_plan(e, result, plan["fingerprint"], race_ids=[legacy.pk])
    before = list(OfficialResult.objects.values())
    again = build_repair_plan(e, result, race_ids=[legacy.pk])
    assert not again["conflicts"]
    assert list(again["race_mapping"]) == [str(filing.pk)]
    apply_repair_plan(e, result, again["fingerprint"], race_ids=[legacy.pk])
    assert list(OfficialResult.objects.values()) == before
