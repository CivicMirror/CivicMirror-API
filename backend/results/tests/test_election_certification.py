"""
Elections move to results_certified once all their races are certified, and date-based syncs can't
move them back.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election, Race


def _election(**overrides):
    fields = dict(
        name="Primary", election_date=date(2026, 9, 1), election_type="primary",
        jurisdiction_level="state", state="MA", canonical_key="MA:primary:2026-09-01:state",
        status=Election.Status.RESULTS_PENDING,
    )
    fields.update(overrides)
    return Election.objects.create(**fields)


def _race(election, n, cert=Race.CertificationStatus.RESULTS_CERTIFIED, status=Race.RaceStatus.ACTIVE):
    return Race.objects.create(
        election=election, race_type=Race.RaceType.CANDIDATE, office_title=f"Office {n}",
        jurisdiction="Massachusetts", geography_scope="statewide", source=Race.Source.CIVIC_API,
        canonical_key=f"t:{election.pk}:{n}", certification_status=cert, race_status=status,
    )


@pytest.mark.django_db
def test_election_certified_when_all_races_certified():
    from results.tasks import _certify_election_if_complete
    e = _election()
    _race(e, 1)
    _race(e, 2)
    assert _certify_election_if_complete(e) is True
    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_CERTIFIED


@pytest.mark.django_db
def test_election_not_certified_while_any_race_pending_or_partial():
    from results.tasks import _certify_election_if_complete
    e = _election()
    _race(e, 1)
    _race(e, 2, cert=Race.CertificationStatus.PARTIAL_RESULTS)
    assert _certify_election_if_complete(e) is False
    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING


@pytest.mark.django_db
def test_cancelled_races_are_ignored_and_empty_elections_untouched():
    from results.tasks import _certify_election_if_complete
    e = _election()
    _race(e, 1)
    _race(e, 2, cert=Race.CertificationStatus.UPCOMING, status=Race.RaceStatus.CANCELLED)
    assert _certify_election_if_complete(e) is True

    empty = _election(canonical_key="MA:primary:2026-09-01:empty")
    assert _certify_election_if_complete(empty) is False


@pytest.mark.django_db
def test_unchanged_ingest_still_certifies_complete_election():
    """Already-complete elections get promoted on their next routine poll even if the source is unchanged."""
    from results.adapters.base import AdapterResult
    from results.tasks import ingest_official_results

    e = _election()
    _race(e, 1)
    adapter = MagicMock()
    adapter.return_value.fetch_results.return_value = AdapterResult(
        rows=[], source_url="", mapping_confidence="full", unchanged=True,
    )
    with patch("results.tasks.get_adapter", return_value=adapter):
        ingest_official_results.run("MA", e.pk)
    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_CERTIFIED


@pytest.mark.django_db
@pytest.mark.parametrize("terminal", [Election.Status.RESULTS_CERTIFIED, Election.Status.ARCHIVED])
def test_date_based_sync_cannot_downgrade_terminal_status(terminal):
    from aggregation import ingest
    from aggregation.models import SourcePrecedence

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="ma_sos", defaults={"rank": 0})
    e = _election(status=terminal)
    election, created = ingest.ingest_election(
        source="ma_sos", source_id="ma_sos_1",
        identity={"state": "MA", "election_type": "primary", "election_date": date(2026, 9, 1),
                  "jurisdiction_level": "state"},
        fields={"name": "Primary", "status": Election.Status.RESULTS_PENDING},
    )
    assert not created and election.pk == e.pk
    e.refresh_from_db()
    assert e.status == terminal


@pytest.mark.django_db
def test_non_terminal_status_still_updates_from_source():
    from aggregation import ingest
    from aggregation.models import SourcePrecedence

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="ma_sos", defaults={"rank": 0})
    e = _election(status=Election.Status.UPCOMING)
    ingest.ingest_election(
        source="ma_sos", source_id="ma_sos_1",
        identity={"state": "MA", "election_type": "primary", "election_date": date(2026, 9, 1),
                  "jurisdiction_level": "state"},
        fields={"name": "Primary", "status": Election.Status.RESULTS_PENDING},
    )
    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING
