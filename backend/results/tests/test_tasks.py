"""
Unit tests for results tasks:
  - poll_pending_results task selection logic
  - ingest_official_results task flow (version cache, retry, no adapter)
  - _process_race_results: candidate match, measure coercion, office_title
    filtering, certification guard, partial match handling
"""
from unittest.mock import MagicMock, call, patch

import pytest
from django.utils import timezone

from elections.models import Candidate, Election, MeasureOption, Race
from results.models import OfficialResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_election(state="WV", status=Election.Status.RESULTS_PENDING, days_ago=10, results_url="https://results.enr.clarityelections.com/WV/126209/"):
    from datetime import date, timedelta
    return Election.objects.create(
        name=f"Test Election {state}",
        election_date=date.today() - timedelta(days=days_ago),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state=state,
        source_id=f"test-{state}-{days_ago}",
        status=status,
        results_url=results_url,
    )


def make_race(election, race_type=Race.RaceType.CANDIDATE, office_title="U.S. Senate", status=Race.CertificationStatus.RESULTS_PENDING):
    return Race.objects.create(
        election=election,
        race_type=race_type,
        office_title=office_title,
        jurisdiction="West Virginia",
        geography_scope="statewide",
        source=Race.Source.CIVIC_API,
        certification_status=status,
    )


def make_result_row(**kwargs):
    from results.adapters.base import ResultRow
    defaults = dict(
        candidate_name="Alice Smith",
        option_label=None,
        vote_count=50000,
        vote_pct=60.0,
        is_winner=True,
        result_type=OfficialResult.ResultType.UNOFFICIAL,
        office_title="U.S. Senate",
    )
    defaults.update(kwargs)
    return ResultRow(**defaults)


def make_adapter_result(rows=None, confidence="full", unchanged=False, source_version=""):
    from results.adapters.base import AdapterResult
    return AdapterResult(
        rows=rows or [],
        source_url="https://example.com/summary.json",
        mapping_confidence=confidence,
        unchanged=unchanged,
        source_version=source_version,
    )


# ---------------------------------------------------------------------------
# poll_pending_results
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@patch("results.tasks.ingest_official_results")
def test_poll_pending_queues_matching_elections(mock_ingest):
    election = make_election(state="WV")
    from results.tasks import poll_pending_results
    with patch("results.tasks.list_supported_states", return_value=["WV", "CO"]):
        result = poll_pending_results()
    assert result["queued"] == 1
    mock_ingest.delay.assert_called_once_with("WV", election.pk)


@pytest.mark.django_db
@patch("results.tasks.ingest_official_results")
def test_poll_pending_skips_unsupported_state(mock_ingest):
    make_election(state="CA")
    from results.tasks import poll_pending_results
    with patch("results.tasks.list_supported_states", return_value=["WV"]):
        result = poll_pending_results()
    assert result["queued"] == 0
    mock_ingest.delay.assert_not_called()


@pytest.mark.django_db
@patch("results.tasks.ingest_official_results")
def test_poll_pending_skips_upcoming_elections(mock_ingest):
    from datetime import date, timedelta
    Election.objects.create(
        name="Future Election",
        election_date=date.today() + timedelta(days=30),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="WV",
        source_id="future-wv",
        status=Election.Status.UPCOMING,
    )
    from results.tasks import poll_pending_results
    with patch("results.tasks.list_supported_states", return_value=["WV"]):
        result = poll_pending_results()
    assert result["queued"] == 0


@pytest.mark.django_db
@patch("results.tasks.ingest_official_results")
def test_poll_pending_no_adapters_returns_zero(mock_ingest):
    make_election(state="WV")
    from results.tasks import poll_pending_results
    with patch("results.tasks.list_supported_states", return_value=[]):
        result = poll_pending_results()
    assert result["queued"] == 0
    mock_ingest.delay.assert_not_called()


# ---------------------------------------------------------------------------
# ingest_official_results
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ingest_no_adapter_returns_early():
    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=None):
        # Should return without error
        ingest_official_results("ZZ", 999)


@pytest.mark.django_db
def test_ingest_unchanged_skips_db_work():
    election = make_election()
    race = make_race(election, status=Race.CertificationStatus.RESULTS_PENDING)

    mock_adapter = MagicMock()
    mock_adapter.fetch_results.return_value = make_adapter_result(unchanged=True, source_version="999")
    mock_adapter.version_cache_key.return_value = f"clarity:ver:{election.pk}"

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=lambda: mock_adapter):
        ingest_official_results("WV", election.pk)

    # Race status should be untouched
    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.RESULTS_PENDING


@pytest.mark.django_db
def test_ingest_version_cache_written_after_db_success():
    election = make_election()
    race = make_race(election)
    _ = Candidate.objects.create(race=race, name="ALICE SMITH")

    row = make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate")
    result = make_adapter_result(rows=[row], source_version="371599")

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.fetch_results.return_value = result
    mock_adapter_instance.version_cache_key.return_value = f"clarity:ver:{election.pk}"
    mock_adapter_instance.VERSION_CACHE_TIMEOUT = 86400 * 30

    mock_adapter_class = MagicMock(return_value=mock_adapter_instance)

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=mock_adapter_class), \
         patch("results.tasks.cache") as mock_cache:
        ingest_official_results("WV", election.pk)

    mock_cache.set.assert_called_once_with(
        f"clarity:ver:{election.pk}", "371599", timeout=86400 * 30
    )


@pytest.mark.django_db
def test_ingest_empty_rows_sets_results_pending():
    election = make_election()
    race = make_race(election, status=Race.CertificationStatus.UPCOMING)

    mock_adapter = MagicMock()
    mock_adapter.fetch_results.return_value = make_adapter_result(rows=[], confidence="full")

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=lambda: mock_adapter):
        ingest_official_results("WV", election.pk)

    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.RESULTS_PENDING


# ---------------------------------------------------------------------------
# _process_race_results: candidate matching
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_race_candidate_match_creates_result():
    election = make_election()
    race = make_race(election)
    candidate = Candidate.objects.create(race=race, name="ALICE SMITH")

    row = make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate")
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    assert OfficialResult.objects.filter(race=race, candidate=candidate).exists()
    or_obj = OfficialResult.objects.get(race=race, candidate=candidate)
    assert or_obj.vote_count == 50000
    assert or_obj.is_winner is True
    assert or_obj.result_type == OfficialResult.ResultType.UNOFFICIAL


@pytest.mark.django_db
def test_process_race_candidate_case_insensitive_match():
    election = make_election()
    race = make_race(election)
    candidate = Candidate.objects.create(race=race, name="Alice Smith")

    row = make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate")
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    assert OfficialResult.objects.filter(race=race, candidate=candidate).exists()


@pytest.mark.django_db
def test_process_race_unmatched_candidate_marks_partial():
    election = make_election()
    race = make_race(election)
    # No Candidate objects created

    row = make_result_row(candidate_name="NOBODY HERE", office_title="U.S. Senate")
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.PARTIAL_RESULTS


# ---------------------------------------------------------------------------
# _process_race_results: measure coercion
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_race_measure_coercion():
    """Clarity uses candidate_name for measure options; should be coerced to option_label."""
    election = make_election()
    race = make_race(election, race_type=Race.RaceType.MEASURE, office_title="AMENDMENT 1")
    opt = MeasureOption.objects.create(race=race, option_label="Yes")

    row = make_result_row(
        candidate_name="Yes",       # Clarity puts this in CH[] for measures
        option_label=None,
        vote_count=30000,
        is_winner=None,
        office_title="AMENDMENT 1",
    )
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    assert OfficialResult.objects.filter(race=race, measure_option=opt).exists()
    or_obj = OfficialResult.objects.get(race=race, measure_option=opt)
    assert or_obj.vote_count == 30000


# ---------------------------------------------------------------------------
# _process_race_results: office_title filtering
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_race_office_title_filter_skips_no_match():
    """When feed has office_titles but none matches this race, skip + mark partial."""
    election = make_election()
    race = make_race(election, office_title="U.S. Senate")
    _ = Candidate.objects.create(race=race, name="Alice")

    # Row belongs to a DIFFERENT contest
    row = make_result_row(candidate_name="Alice", office_title="GOVERNOR")
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    # No OfficialResult should be created
    assert not OfficialResult.objects.filter(race=race).exists()
    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.PARTIAL_RESULTS


@pytest.mark.django_db
def test_process_race_no_office_titles_uses_all_rows():
    """When feed has no office_titles, fall back to all rows (non-Clarity adapters)."""
    election = make_election()
    race = make_race(election)
    candidate = Candidate.objects.create(race=race, name="Alice Smith")

    row = make_result_row(candidate_name="Alice Smith", office_title=None)
    result = make_adapter_result(rows=[row])

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    assert OfficialResult.objects.filter(race=race, candidate=candidate).exists()


@pytest.mark.django_db
def test_process_race_prefers_source_contest_identity_over_office_title():
    election = make_election(state="AL")
    dem_race = make_race(
        election,
        office_title="UNITED STATES SENATOR",
        status=Race.CertificationStatus.RESULTS_PENDING,
    )
    dem_race.source_metadata = {
        "bootstrapped_from": "results_adapter",
        "state": "AL",
        "contest_code": "001",
        "party_code": "DEM",
    }
    dem_race.save(update_fields=["source_metadata"])
    dem_candidate = Candidate.objects.create(race=dem_race, name="JOHN SMITH")
    rep_race = make_race(
        election,
        office_title="UNITED STATES SENATOR",
        status=Race.CertificationStatus.RESULTS_PENDING,
    )
    rep_race.source_metadata = {
        "bootstrapped_from": "results_adapter",
        "state": "AL",
        "contest_code": "002",
        "party_code": "REP",
    }
    rep_race.save(update_fields=["source_metadata"])
    rep_candidate = Candidate.objects.create(race=rep_race, name="JOHN SMITH")

    result = make_adapter_result(rows=[
        make_result_row(
            candidate_name="JOHN SMITH",
            office_title="UNITED STATES SENATOR",
            vote_count=100,
            raw={"contest_code": "001", "party_code": "DEM"},
        ),
        make_result_row(
            candidate_name="JOHN SMITH",
            office_title="UNITED STATES SENATOR",
            vote_count=200,
            raw={"contest_code": "002", "party_code": "REP"},
        ),
    ])

    from results.tasks import _process_race_results
    _process_race_results(dem_race, result, "AL")
    _process_race_results(rep_race, result, "AL")

    assert OfficialResult.objects.get(race=dem_race, candidate=dem_candidate).vote_count == 100
    assert OfficialResult.objects.get(race=rep_race, candidate=rep_candidate).vote_count == 200


# ---------------------------------------------------------------------------
# _process_race_results: certification guard — UNOFFICIAL results should not
# advance race to RESULTS_CERTIFIED
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_process_race_unofficial_result_sets_pending_not_certified():
    election = make_election()
    race = make_race(election)
    _ = Candidate.objects.create(race=race, name="Alice Smith")

    row = make_result_row(
        candidate_name="Alice Smith",
        office_title="U.S. Senate",
        result_type=OfficialResult.ResultType.UNOFFICIAL,
    )
    result = make_adapter_result(rows=[row], confidence="full")

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    race.refresh_from_db()
    # Must NOT be certified just because confidence=full
    assert race.certification_status == Race.CertificationStatus.RESULTS_PENDING
    assert race.race_status != Race.RaceStatus.ARCHIVED


@pytest.mark.django_db
def test_process_race_official_result_sets_certified():
    election = make_election()
    race = make_race(election)
    _ = Candidate.objects.create(race=race, name="Alice Smith")

    row = make_result_row(
        candidate_name="Alice Smith",
        office_title="U.S. Senate",
        result_type=OfficialResult.ResultType.OFFICIAL,
    )
    result = make_adapter_result(rows=[row], confidence="full")

    from results.tasks import _process_race_results
    _process_race_results(race, result, "WV")

    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED
    assert race.race_status == Race.RaceStatus.ARCHIVED


# ---------------------------------------------------------------------------
# _bootstrap_races_from_results
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_bootstrap_creates_candidate_race():
    election = make_election()
    rows = [
        make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate"),
        make_result_row(candidate_name="BOB JONES", office_title="U.S. Senate"),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    assert len(created) == 1
    race = created[0]
    assert race.office_title == "U.S. Senate"
    assert race.race_type == Race.RaceType.CANDIDATE
    assert race.source == Race.Source.RESULTS_ADAPTER
    assert race.match_confidence == Race.MatchConfidence.LOW
    assert Candidate.objects.filter(race=race).count() == 2
    names = set(Candidate.objects.filter(race=race).values_list('name', flat=True))
    assert names == {"ALICE SMITH", "BOB JONES"}


@pytest.mark.django_db
def test_bootstrap_detects_measure_race_from_title():
    election = make_election()
    rows = [
        make_result_row(candidate_name="Yes", option_label=None, office_title="Amendment 1"),
        make_result_row(candidate_name="No", option_label=None, office_title="Amendment 1"),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    assert len(created) == 1
    race = created[0]
    assert race.race_type == Race.RaceType.MEASURE
    opts = set(MeasureOption.objects.filter(race=race).values_list('option_label', flat=True))
    assert opts == {"Yes", "No"}


@pytest.mark.django_db
def test_bootstrap_multiple_offices():
    election = make_election()
    rows = [
        make_result_row(candidate_name="ALICE", office_title="U.S. Senate"),
        make_result_row(candidate_name="BOB", office_title="U.S. Senate"),
        make_result_row(candidate_name="CAROL", office_title="Governor"),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    assert len(created) == 2
    titles = {r.office_title for r in created}
    assert titles == {"U.S. Senate", "Governor"}


@pytest.mark.django_db
def test_bootstrap_preserves_al_contest_identity_for_same_stripped_title():
    election = make_election(state="AL")
    rows = [
        make_result_row(
            candidate_name="JOHN SMITH",
            office_title="UNITED STATES SENATOR",
            vote_count=100,
            raw={"contest_code": "001", "party_code": "DEM"},
        ),
        make_result_row(
            candidate_name="JOHN SMITH",
            office_title="UNITED STATES SENATOR",
            vote_count=200,
            raw={"contest_code": "002", "party_code": "REP"},
        ),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results, _process_race_results
    created = _bootstrap_races_from_results(election, result, "AL")

    assert len(created) == 2
    assert {race.office_title for race in created} == {"UNITED STATES SENATOR"}
    identities = {
        (race.source_metadata["contest_code"], race.source_metadata["party_code"])
        for race in created
    }
    assert identities == {("001", "DEM"), ("002", "REP")}

    for race in created:
        _process_race_results(race, result, "AL")

    results_by_identity = {
        (official.race.source_metadata["contest_code"], official.race.source_metadata["party_code"]): official.vote_count
        for official in OfficialResult.objects.filter(race__in=created).select_related("race")
    }
    assert results_by_identity == {("001", "DEM"): 100, ("002", "REP"): 200}


@pytest.mark.django_db
def test_bootstrap_does_not_split_generic_rows_by_party_code_only():
    election = make_election(state="FL")
    rows = [
        make_result_row(
            candidate_name="ALICE DEM",
            office_title="Governor",
            raw={"party_code": "DEM"},
        ),
        make_result_row(
            candidate_name="BOB REP",
            office_title="Governor",
            raw={"party_code": "REP"},
        ),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "FL")

    assert len(created) == 1
    race = created[0]
    assert race.office_title == "Governor"
    assert "party_code" not in race.source_metadata
    names = set(Candidate.objects.filter(race=race).values_list("name", flat=True))
    assert names == {"ALICE DEM", "BOB REP"}


@pytest.mark.django_db
def test_bootstrap_skips_rows_with_no_office_title():
    election = make_election()
    rows = [
        make_result_row(candidate_name="ALICE", office_title=None),
        make_result_row(candidate_name="BOB", office_title="U.S. Senate"),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    assert len(created) == 1
    assert created[0].office_title == "U.S. Senate"


@pytest.mark.django_db
def test_bootstrap_returns_existing_races_when_already_bootstrapped():
    """Idempotency: if races already exist, bootstrap returns them without creating duplicates."""
    election = make_election()
    existing_race = make_race(election, office_title="U.S. Senate")
    rows = [make_result_row(candidate_name="ALICE", office_title="U.S. Senate")]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    returned = _bootstrap_races_from_results(election, result, "WV")

    assert len(returned) == 1
    assert returned[0].pk == existing_race.pk
    assert Race.objects.filter(election=election).count() == 1


@pytest.mark.django_db
def test_bootstrap_write_in_candidate_status():
    election = make_election()
    rows = [
        make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate", is_write_in_aggregate=False),
        make_result_row(candidate_name="WRITE-IN", office_title="U.S. Senate", is_write_in_aggregate=True),
    ]
    result = make_adapter_result(rows=rows)

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    race = created[0]
    wi = Candidate.objects.get(race=race, name="WRITE-IN")
    assert wi.candidate_status == Candidate.CandidateStatus.WRITE_IN
    alice = Candidate.objects.get(race=race, name="ALICE SMITH")
    assert alice.candidate_status == Candidate.CandidateStatus.RUNNING


@pytest.mark.django_db
def test_bootstrap_empty_rows_returns_empty():
    election = make_election()
    result = make_adapter_result(rows=[])

    from results.tasks import _bootstrap_races_from_results
    created = _bootstrap_races_from_results(election, result, "WV")

    assert created == []
    assert Race.objects.filter(election=election).count() == 0


# ---------------------------------------------------------------------------
# ingest_official_results: bootstrap integration
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ingest_bootstrap_creates_races_and_results_when_none_exist():
    """Full integration: election with no races gets bootstrapped + results stored."""
    election = make_election()

    rows = [make_result_row(candidate_name="ALICE SMITH", office_title="U.S. Senate")]
    result = make_adapter_result(rows=rows, source_version="999")

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.fetch_results.return_value = result
    mock_adapter_instance.version_cache_key.return_value = f"clarity:ver:{election.pk}"
    mock_adapter_instance.VERSION_CACHE_TIMEOUT = 86400 * 30
    mock_adapter_class = MagicMock(return_value=mock_adapter_instance)

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=mock_adapter_class), \
         patch("results.tasks.cache") as mock_cache:
        mock_cache.get.return_value = None  # no stale version
        ingest_official_results("WV", election.pk)

    # Race and candidate were bootstrapped
    assert Race.objects.filter(election=election).count() == 1
    race = Race.objects.get(election=election)
    assert race.race_type == Race.RaceType.CANDIDATE
    assert race.source == Race.Source.RESULTS_ADAPTER
    assert Candidate.objects.filter(race=race, name="ALICE SMITH").exists()
    # OfficialResult was written
    assert OfficialResult.objects.filter(race=race).exists()


@pytest.mark.django_db
def test_ingest_clears_stale_version_cache_when_no_races():
    """If version cache exists but there are no races, it must be cleared before fetch."""
    election = make_election()

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.fetch_results.return_value = make_adapter_result(rows=[])
    mock_adapter_instance.version_cache_key.return_value = f"clarity:ver:{election.pk}"
    mock_adapter_instance.VERSION_CACHE_TIMEOUT = 86400 * 30
    mock_adapter_class = MagicMock(return_value=mock_adapter_instance)

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=mock_adapter_class), \
         patch("results.tasks.cache") as mock_cache:
        mock_cache.get.return_value = "stale-ver-123"  # stale cached version
        ingest_official_results("WV", election.pk)

    mock_cache.delete.assert_called_once_with(f"clarity:ver:{election.pk}")


@pytest.mark.django_db
def test_ingest_version_cache_not_written_when_bootstrap_finds_no_rows():
    """Version cache must NOT be written when no races were processed."""
    election = make_election()

    mock_adapter_instance = MagicMock()
    # Adapter returns rows but bootstrap produces nothing (all titles empty)
    mock_adapter_instance.fetch_results.return_value = make_adapter_result(
        rows=[make_result_row(candidate_name="ALICE", office_title=None)],
        source_version="777",
    )
    mock_adapter_instance.version_cache_key.return_value = f"clarity:ver:{election.pk}"
    mock_adapter_instance.VERSION_CACHE_TIMEOUT = 86400 * 30
    mock_adapter_class = MagicMock(return_value=mock_adapter_instance)

    from results.tasks import ingest_official_results
    with patch("results.tasks.get_adapter", return_value=mock_adapter_class), \
         patch("results.tasks.cache") as mock_cache:
        mock_cache.get.return_value = None
        ingest_official_results("WV", election.pk)

    # No races created, so version cache must NOT be written
    mock_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# OfficialResult natural-key uniqueness
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_duplicate_official_result_insert_rejected():
    """Concurrent retries must not be able to insert duplicate result rows
    for the same (race, candidate, measure_option, round, fragment) key."""
    from django.db import IntegrityError

    election = make_election()
    race = make_race(election)
    candidate = Candidate.objects.create(race=race, name="Alice Smith")

    OfficialResult.objects.create(race=race, candidate=candidate, vote_count=100)
    with pytest.raises(IntegrityError):
        OfficialResult.objects.create(race=race, candidate=candidate, vote_count=100)


@pytest.mark.django_db
def test_distinct_rounds_and_fragments_still_allowed():
    election = make_election()
    race = make_race(election)
    candidate = Candidate.objects.create(race=race, name="Alice Smith")

    OfficialResult.objects.create(race=race, candidate=candidate, vote_count=100)
    OfficialResult.objects.create(race=race, candidate=candidate, vote_count=90, round_number=2)
    OfficialResult.objects.create(
        race=race, candidate=candidate, vote_count=40, jurisdiction_fragment="Kanawha"
    )
    assert OfficialResult.objects.filter(race=race).count() == 3
