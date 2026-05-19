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
