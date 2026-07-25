"""
Tests for integrations.ma_sos.tasks — Celery task unit tests.
All DB and HTTP calls are mocked. No real DB or network required.
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest
from django.test import override_settings

# ---------------------------------------------------------------------------
# _SYNC_STAGES
# ---------------------------------------------------------------------------

def test_sync_stages_party_slugs_precede_generic_primaries():
    """Discovery dedupes by election_id keeping the first-seen row (see
    sync_ma_elections). electionstats returns the same election_id under both
    its party-specific stage and the generic "Primaries" stage, so the
    party-specific stage must be queried first for the party label / Race
    split (mappers.contest_variant_key) to survive dedup."""
    from integrations.ma_sos.tasks import _SYNC_STAGES

    assert "Primaries" in _SYNC_STAGES
    party_stages = ["Democratic", "Republican", "Green-Rainbow", "Libertarian",
                     "Working Families", "United Independent", "American", "Independent Voters"]
    primaries_idx = _SYNC_STAGES.index("Primaries")
    for stage in party_stages:
        assert stage in _SYNC_STAGES
        assert _SYNC_STAGES.index(stage) < primaries_idx


# ---------------------------------------------------------------------------
# sync_ma_elections
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.sync_ma_races")
@patch("integrations.ma_sos.tasks.sync_ma_ballot_question")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_discovers_and_queues(
    mock_tz, mock_client_cls, mock_bq_task, mock_races_task,
    mock_synclog_cls,
):
    """Routing through ingest_election: verify races + BQ tasks are queued when
    a valid election is discovered.  Election model calls now go through the
    aggregation ingest service, so we mock that instead of bulk_create."""
    from integrations.ma_sos.tasks import sync_ma_elections

    # SyncLog setup
    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"
    mock_synclog_cls.Status.FAILED = "failed"

    # Client returns 1 election and 1 BQ
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ocpf_schedule.return_value = {"generalElectionDate": "11/5/2024", "primaryElectionDate": "9/3/2024"}

    def fake_get_election_ids(year, stage):
        if year == 2024 and stage == "General":
            return [{"election_id": 165300, "office": "President", "district": "", "stage": "General", "year": 2024}]
        return []

    mock_client.get_election_ids.side_effect = fake_get_election_ids
    mock_client.get_ballot_question_ids.return_value = [11620]

    # Mock the ingest service to return a fake election object
    mock_saved_election = MagicMock()
    mock_saved_election.pk = 1
    mock_saved_election.source_metadata = {"electionstats_id": 165300}

    mock_tz.now.return_value = MagicMock()
    mock_tz.localdate.return_value = date(2024, 12, 1)

    # Patch date.today() and the ingest service
    with patch("integrations.ma_sos.tasks.date") as mock_date, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_saved_election, True)):
        mock_date.today.return_value = date(2024, 12, 1)
        sync_ma_elections.run()

    # Task should have queued at least one races task and one BQ task
    mock_races_task.apply_async.assert_called()
    mock_bq_task.apply_async.assert_called()


@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_empty_returns_warning(mock_tz, mock_client_cls, mock_synclog_cls):
    from integrations.ma_sos.tasks import sync_ma_elections

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ocpf_schedule.return_value = {}
    mock_client.get_election_ids.return_value = []
    mock_client.get_ballot_question_ids.return_value = []

    mock_tz.now.return_value = MagicMock()

    with patch("integrations.ma_sos.tasks.date") as mock_date:
        mock_date.today.return_value = date(2024, 12, 1)
        result = sync_ma_elections.run()

    assert result["created"] == 0
    mock_log.save.assert_called()


# ---------------------------------------------------------------------------
# sync_ma_races
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_upserts_race_and_candidates(
    mock_tz, mock_client_cls, mock_election_cls, mock_synclog_cls,
):
    """sync_ma_races routes through ingest_race + ingest_candidate (not bulk_create).
    Adapted from OLD bulk_create pattern: now mocks the aggregation ingest service."""
    from integrations.ma_sos.tasks import sync_ma_races

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"

    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_165323"
    mock_election.source_metadata = {"electionstats_id": 165323, "office": "U.S. House", "district": "1st Congressional", "stage": "General"}
    mock_election.name = "2024 MA U.S. House 1st Congressional General"
    mock_election.status = "results_pending"
    mock_election.state = "MA"
    mock_election.canonical_key = "MA:general:2024-11-05:state"
    mock_election_cls.objects.get.return_value = mock_election
    mock_election_cls.Status.UPCOMING = "upcoming"
    mock_election_cls.Status.ACTIVE = "active"
    mock_election_cls.Status.RESULTS_PENDING = "results_pending"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    csv_bytes = (
        b'City/Town,,,"Richard E. Neal","Opponent","All Others","Blanks","Total Votes Cast"\r\n'
        b',,,Democratic,Republican,,,\r\n'
        b'Abington,,,"1000","500",5,10,"1515"\r\n'
        b'TOTALS,,,"1000","500",5,10,"1515"\r\n'
    )
    mock_client.download_election_csv.return_value = csv_bytes

    mock_race_obj = MagicMock()
    mock_tz.now.return_value = MagicMock()

    with patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_ingest_cand:
        sync_ma_races.run(1, 165323)

    # Verify ingest_race was called once (one race per election CSV)
    mock_ingest_race.assert_called_once()
    # Verify ingest_candidate was called twice (two real candidates)
    assert mock_ingest_cand.call_count == 2


@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_missing_election_returns(mock_tz, mock_election_cls, mock_synclog_cls):
    from elections.models import Election as RealElection
    from integrations.ma_sos.tasks import sync_ma_races

    mock_election_cls.DoesNotExist = RealElection.DoesNotExist
    mock_election_cls.objects.get.side_effect = RealElection.DoesNotExist()
    mock_tz.now.return_value = MagicMock()

    result = sync_ma_races.run(99999, 12345)
    assert result is None


# ---------------------------------------------------------------------------
# sync_ma_ballot_question
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.MeasureOption")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks._get_or_create_bq_election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_ballot_question_upserts(
    mock_tz, mock_get_election, mock_client_cls,
    mock_measure_cls, mock_synclog_cls,
):
    """sync_ma_ballot_question routes through ingest_race (not bulk_create).
    Adapted from OLD bulk_create pattern: now mocks aggregation.ingest.ingest_race."""
    from integrations.ma_sos.tasks import sync_ma_ballot_question

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ballot_question_metadata.return_value = {
        "bq_id": 11620,
        "question_number": "1",
        "question": "Do you approve?",
        "question_alias": "Audit",
        "summary": "Short",
        "is_initiative_petition": True,
        "is_referendum": False,
        "is_local": False,
        "is_county": False,
        "date": "2024-11-05",
        "year": 2024,
    }

    mock_election = MagicMock()
    mock_election.status = "results_pending"
    mock_election.canonical_key = "MA:general:2024-11-05:state"
    mock_election.state = "MA"
    mock_get_election.return_value = mock_election

    mock_race_obj = MagicMock()
    mock_tz.now.return_value = MagicMock()

    with patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race:
        sync_ma_ballot_question.run(11620)

    # Verify ingest_race was called with source="ma_sos" and race_type="measure"
    mock_ingest_race.assert_called_once()
    call_kwargs = mock_ingest_race.call_args.kwargs
    assert call_kwargs["source"] == "ma_sos"
    assert call_kwargs["identity"]["race_type"] == "measure"
    # Yes/No MeasureOptions are still created outside the merge layer
    assert mock_measure_cls.objects.get_or_create.call_count == 2


# ---------------------------------------------------------------------------
# Integration test — ingest service routing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_elections_routes_through_ingest_service():
    """Verify each discovered MA election lands as a canonical Election via the
    aggregation ingest service with electionstats_id preserved on source_metadata."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, ElectionSourceLink
    from integrations.ma_sos.tasks import sync_ma_elections

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    fake_rows = [
        {"election_id": 165300, "office": "President", "district": "Statewide",
         "stage": "General", "year": 2024},
    ]

    # The two task patches prevent .delay() side effects; their bindings
    # aren't asserted on.
    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient, \
         patch("integrations.ma_sos.tasks.sync_ma_races"), \
         patch("integrations.ma_sos.tasks.sync_ma_ballot_question"):
        inst = MockClient.return_value
        inst.get_ocpf_schedule.return_value = {"generalElectionDate": "11/5/2024", "primaryElectionDate": "9/3/2024"}
        inst.get_election_ids.return_value = fake_rows
        inst.get_ballot_question_ids.return_value = []
        sync_ma_elections.run()

    e = Election.objects.get(state="MA", election_date=date(2024, 11, 5))
    assert "ma_sos" in e.contributing_sources
    assert e.canonical_key.startswith("MA:")
    link = ElectionSourceLink.objects.get(election=e, source="ma_sos")
    assert link.source_id  # populated by ingest
    assert e.source_metadata.get("electionstats_id") == 165300


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_races_routes_through_ingest_service():
    """sync_ma_races writes a canonical Race + Candidates via the aggregation
    ingest service (not bulk_create)."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ma_races

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    e = Election.objects.create(
        name="2024 MA U.S. House 1st Congressional General",
        election_date=date(2024, 11, 5),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        canonical_key="MA:general:2024-11-05:state",
        source_metadata={"electionstats_id": 165323, "office": "U.S. House", "district": "1", "stage": "General"},
        contributing_sources=["ma_sos"],
    )

    fake_csv = (
        b'City/Town,,,"Smith, John","Doe, Jane",All Others,Blanks,Total Votes Cast\n'
        b',,,Democratic,Republican,,,,\n'
        b'Boston,,,"1,000","800",5,10,"1,815"\n'
        b'TOTALS,,,"1,000","800",5,10,"1,815"\n'
    )

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.download_election_csv.return_value = fake_csv
        sync_ma_races.run(e.pk, 165323)

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert race.canonical_key is not None
    assert race.canonical_key.startswith("MA:general:2024-11-05:state|")
    assert "ma_sos" in race.contributing_sources
    assert Candidate.objects.filter(race=race).count() == 2


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_races_splits_primary_by_party():
    """A Democratic-stage and a Republican-stage primary for the same office
    and date share one canonical Election (same type/date/jurisdiction) but
    must land as two distinct Races, each with correctly-attributed party —
    the merged-race bug from issue #105."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ma_races

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    e = Election.objects.create(
        name="2026 MA State Representative 5th Essex Special Primary",
        election_date=date(2026, 9, 1),
        election_type="primary",
        jurisdiction_level="state",
        state="MA",
        canonical_key="MA:primary:2026-09-01:state",
        contributing_sources=["ma_sos"],
    )

    dem_csv = (
        b'City/Town,,,"Andrew Tarr","Sarah Wilkinson",All Others,Blanks,Total Votes Cast\n'
        b',,,,,,,\n'
        b'Boston,,,"2,194","879",30,23,"3,126"\n'
        b'TOTALS,,,"2,194","879",30,23,"3,126"\n'
    )
    rep_csv = (
        b'City/Town,,,"Christina Delisio","Ashley Sullivan",All Others,Blanks,Total Votes Cast\n'
        b',,,,,,,\n'
        b'Boston,,,"568","356",37,6,"967"\n'
        b'TOTALS,,,"568","356",37,6,"967"\n'
    )

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.download_election_csv.side_effect = [dem_csv, rep_csv]
        sync_ma_races.run(e.pk, 171921, "State Representative", "5th Essex", "Democratic")
        sync_ma_races.run(e.pk, 171922, "State Representative", "5th Essex", "Republican")

    races = Race.objects.filter(election=e).order_by("canonical_key")
    assert races.count() == 2

    dem_race = next(r for r in races if r.candidates.filter(name="Andrew Tarr").exists())
    rep_race = next(r for r in races if r.candidates.filter(name="Christina Delisio").exists())
    assert dem_race.pk != rep_race.pk

    assert Candidate.objects.get(race=dem_race, name="Andrew Tarr").party == "Democratic"
    assert Candidate.objects.get(race=dem_race, name="Sarah Wilkinson").party == "Democratic"
    assert Candidate.objects.get(race=rep_race, name="Christina Delisio").party == "Republican"
    assert Candidate.objects.get(race=rep_race, name="Ashley Sullivan").party == "Republican"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_ballot_question_routes_through_ingest_service():
    """sync_ma_ballot_question writes a canonical measure Race (+ Yes/No options) via ingest."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, MeasureOption, Race
    from integrations.ma_sos.tasks import sync_ma_ballot_question

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    # Pre-seed the BQ-parent Election so _get_or_create_bq_election finds it.
    e = Election.objects.create(
        name="2024 MA Ballot Questions",
        election_date=date(2024, 11, 5),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        canonical_key="MA:general:2024-11-05:state",
        contributing_sources=["ma_sos"],
    )

    fake_metadata = {
        "bq_id": 11620,
        "date": "2024-11-05",
        "year": 2024,
        "title": "Question 1 — State Auditor authority to audit Legislature",
        "summary": "Sample summary",
    }

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_ballot_question_metadata.return_value = fake_metadata
        sync_ma_ballot_question.run(11620)

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert race.race_type == "measure"
    assert race.canonical_key.startswith("MA:general:2024-11-05:state|")
    assert "ma_sos" in race.contributing_sources
    # Yes/No options are still created via get_or_create (outside the merge layer).
    labels = set(MeasureOption.objects.filter(race=race).values_list("option_label", flat=True))
    assert {"Yes", "No"}.issubset(labels)


# ---------------------------------------------------------------------------
# sync_ocpf_ma_candidates
# ---------------------------------------------------------------------------

_TARR_DEPOSITORY_ROW = {
    "cpfId": 19580,
    "filerName": "Tarr, Andrew",
    "officeSought": "5th Essex",
    "receiptsYtdNumeric": 28366.76,
    "expendituresYtdNumeric": 32967.91,
    "currentCashOnHandNumeric": 9824.71,
    "partyAffiliation": "Democratic",
    "isWinner": False,
}

_TARR_FILER_DETAIL = {
    "cpfId": 19580,
    "candidateLastName": "Tarr",
    "fullName": "Andrew F. Tarr",
    "committeeName": "Tarr Committee",
    "candidate": {"fullAddress": "215 Washington St Gloucester, MA  01930"},
    "officeSought": {"officeDescription": "House", "districtDescription": "5th Essex"},
    "partyAffiliation": "Democratic",
    "tags": [{"tagTypeDescription": "On Ballot", "year": 2026}],
    "filerPhotoUrl": "",
}


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_enriches_existing_candidate():
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates
    from ops.models import SyncLog

    election = Election.objects.create(
        name="2026 MA State Representative 5th Essex",
        election_date=date(2026, 11, 3),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        source_id="ma-2026-5th-essex",
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative",
        jurisdiction="5th Essex",
        geography_scope="district",
        source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key="ma-house-5th-essex",
        normalized_office_title="state representative",
    )
    candidate = Candidate.objects.create(race=race, name="Andrew Francis Robert Tarr")

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [_TARR_DEPOSITORY_ROW]
        inst.get_filer_detail.return_value = _TARR_FILER_DETAIL

        result = sync_ocpf_ma_candidates.run(2026)

    candidate.refresh_from_db()
    sync_log = SyncLog.objects.get(task_name="sync_ocpf_ma_candidates")
    assert result["updated"] == 1
    assert candidate.ocpf_filer_id == "19580"
    assert candidate.party == "Democratic"
    assert candidate.contact_office == "215 Washington St Gloucester, MA  01930"
    assert "ocpf" in candidate.contributing_sources
    assert candidate.source_metadata["ocpf"]["on_ballot"] is True
    assert sync_log.records_updated == 1
    assert sync_log.status == SyncLog.Status.COMPLETED


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_incumbent_office_not_overwritten():
    """Confirms the incumbent-conditional priority is actually wired through
    the real task, not just unit-tested in isolation on CandidateMatcher."""
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates

    election = Election.objects.create(
        name="2026 MA State Representative 5th Essex",
        election_date=date(2026, 11, 3),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        source_id="ma-2026-5th-essex-2",
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative",
        jurisdiction="5th Essex",
        geography_scope="district",
        source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key="ma-house-5th-essex-2",
        normalized_office_title="state representative",
    )
    candidate = Candidate.objects.create(
        race=race, name="Andrew Francis Robert Tarr", incumbent=True,
    )
    # Simulate openstates having already set the real Capitol office.
    from integrations.orchestrator.candidate_matcher import CandidateMatcher
    CandidateMatcher().enrich(race, "openstates", "os-1", {"name": "Andrew Francis Robert Tarr", "contact_office": "Room 39, State House"})

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [_TARR_DEPOSITORY_ROW]
        inst.get_filer_detail.return_value = _TARR_FILER_DETAIL

        sync_ocpf_ma_candidates.run(2026)

    candidate.refresh_from_db()
    assert candidate.contact_office == "Room 39, State House"


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_skips_row_without_cpf_id():
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [{"filerName": "No, Id"}]

        result = sync_ocpf_ma_candidates.run(2026)

    assert result["skipped"] == 1
    assert result["updated"] == 0


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_empty_depository_returns_warning():
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates
    from ops.models import SyncLog

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = []

        result = sync_ocpf_ma_candidates.run(2026)

    sync_log = SyncLog.objects.get(task_name="sync_ocpf_ma_candidates")
    assert result == {"updated": 0, "skipped": 0, "warnings": 0}
    assert sync_log.status == SyncLog.Status.COMPLETED_WITH_WARNINGS


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_no_match_is_skipped_not_error():
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [_TARR_DEPOSITORY_ROW]
        inst.get_filer_detail.return_value = _TARR_FILER_DETAIL

        result = sync_ocpf_ma_candidates.run(2026)

    assert result["updated"] == 0
    assert result["skipped"] == 1


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_enriches_both_primary_and_general_rows():
    """
    Regression test for the real production gap this fix closes: a candidate
    who wins a contested primary has two separate Candidate rows for the
    same office (primary Race + general Race). OCPF's per-year depository
    doesn't distinguish between them, so matching state+chamber-wide (the
    old behavior) always called this ambiguous and enriched neither row.
    Confirmed live for Andrew Tarr / Christina Delisio (issue #26) before
    this fix — both were skipped as ambiguous in production.
    """
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates

    primary_election = Election.objects.create(
        name="2026 MA State Representative 5th Essex Primary",
        election_date=date(2026, 9, 1),
        election_type="primary",
        jurisdiction_level="state",
        state="MA",
        source_id="ma-2026-5th-essex-primary",
    )
    primary_race = Race.objects.create(
        election=primary_election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative",
        jurisdiction="5th Essex",
        geography_scope="district",
        source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key="ma-house-5th-essex-primary",
        normalized_office_title="state representative",
    )
    general_election = Election.objects.create(
        name="2026 MA State Representative 5th Essex",
        election_date=date(2026, 11, 3),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        source_id="ma-2026-5th-essex-general",
    )
    general_race = Race.objects.create(
        election=general_election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative",
        jurisdiction="5th Essex",
        geography_scope="district",
        source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key="ma-house-5th-essex-general",
        normalized_office_title="state representative",
    )
    primary_candidate = Candidate.objects.create(race=primary_race, name="Andrew Francis Robert Tarr")
    general_candidate = Candidate.objects.create(race=general_race, name="Andrew Francis Robert Tarr")

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [_TARR_DEPOSITORY_ROW]
        inst.get_filer_detail.return_value = _TARR_FILER_DETAIL

        result = sync_ocpf_ma_candidates.run(2026)

    primary_candidate.refresh_from_db()
    general_candidate.refresh_from_db()
    assert result["updated"] == 2
    assert result["warnings"] == 0
    assert primary_candidate.party == "Democratic"
    assert general_candidate.party == "Democratic"
    assert primary_candidate.ocpf_filer_id == "19580"
    assert general_candidate.ocpf_filer_id == "19580"


@pytest.mark.django_db
def test_sync_ocpf_ma_candidates_scopes_to_year():
    """A same-district race from a different year must not match."""
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ocpf_ma_candidates

    old_election = Election.objects.create(
        name="2022 MA State Representative 5th Essex",
        election_date=date(2022, 11, 8),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        source_id="ma-2022-5th-essex",
    )
    old_race = Race.objects.create(
        election=old_election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative",
        jurisdiction="5th Essex",
        geography_scope="district",
        source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key="ma-house-5th-essex-2022",
        normalized_office_title="state representative",
    )
    Candidate.objects.create(race=old_race, name="Andrew Francis Robert Tarr")

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_legislative_depository.return_value = [_TARR_DEPOSITORY_ROW]
        inst.get_filer_detail.return_value = _TARR_FILER_DETAIL

        result = sync_ocpf_ma_candidates.run(2026)

    assert result["updated"] == 0
    assert result["skipped"] == 1
