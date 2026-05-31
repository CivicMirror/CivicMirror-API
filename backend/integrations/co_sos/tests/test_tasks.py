"""
Tests for Colorado SOS Celery tasks.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.co_sos.tasks import _current_even_year


class TestCurrentEvenYear:
    def test_returns_even_year_when_current_is_even(self):
        with patch("integrations.co_sos.tasks.timezone") as mock_tz:
            mock_tz.localdate.return_value = date(2026, 5, 1)
            mock_tz.now = MagicMock()
            assert _current_even_year() == 2026

    def test_returns_next_even_year_when_current_is_odd(self):
        with patch("integrations.co_sos.tasks.timezone") as mock_tz:
            mock_tz.localdate.return_value = date(2025, 5, 1)
            mock_tz.now = MagicMock()
            assert _current_even_year() == 2026


@pytest.mark.django_db
class TestSyncCoElectionsTask:
    def test_seeds_election_and_queues_candidates_on_changed_page(self):
        from elections.models import ElectionSourceLink
        from integrations.co_sos.tasks import sync_co_elections

        fingerprint = "abc123"

        with (
            patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
            patch("integrations.co_sos.tasks.cache") as mock_cache,
            patch("integrations.co_sos.tasks.sync_co_candidates") as mock_stage2,
        ):
            MockClient.return_value.get_candidate_page_fingerprint.return_value = fingerprint
            mock_cache.get.return_value = None  # page looks new
            mock_cache.add = MagicMock()

            result = sync_co_elections.apply().get()

        assert result["created"] >= 1
        assert ElectionSourceLink.objects.filter(
            source="co_sos", source_id="co_sos_2026_primary"
        ).exists()
        mock_stage2.delay.assert_called_once()

    def test_skips_candidates_when_page_unchanged(self):
        from integrations.co_sos.tasks import sync_co_elections

        with (
            patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
            patch("integrations.co_sos.tasks.cache") as mock_cache,
            patch("integrations.co_sos.tasks.sync_co_candidates") as mock_stage2,
        ):
            MockClient.return_value.get_candidate_page_fingerprint.return_value = "fp"
            mock_cache.get.return_value = "fp"  # unchanged
            mock_cache.add = MagicMock()

            result = sync_co_elections.apply().get()

        assert result["queued"] == 0
        mock_stage2.delay.assert_not_called()


@pytest.mark.django_db
class TestSyncCoCandidatesTask:
    def _make_election(self):
        from elections.models import Election
        return Election.objects.create(
            source_id="co_sos_2026_primary",
            name="2026 Colorado Primary Election",
            election_date=date(2026, 6, 30),
            jurisdiction_level="state",
            state="CO",
            status=Election.Status.UPCOMING,
        )

    def _candidate_html(self):
        return """
        <html><body><table>
          <tr>
            <th scope='col'>Candidate name</th>
            <th scope='col'>Office</th>
            <th scope='col'>District</th>
            <th scope='col'>Party</th>
            <th scope='col'>Write in?</th>
          </tr>
          <tr>
            <td>John Smith</td><td>Governor</td><td>Statewide</td><td>Democratic Party</td><td>N</td>
          </tr>
          <tr>
            <td>Jane Doe</td><td>Governor</td><td>Statewide</td><td>Republican Party</td><td>N</td>
          </tr>
        </table></body></html>
        """

    def test_creates_races_and_candidates(self):
        from aggregation.models import SourcePrecedence
        from elections.models import Candidate, Race
        from integrations.co_sos.tasks import sync_co_candidates

        SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})
        election = self._make_election()

        with (
            patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
            patch("integrations.co_sos.tasks.cache") as mock_cache,
        ):
            MockClient.return_value.fetch_candidate_html.return_value = self._candidate_html()
            mock_cache.set = MagicMock()

            result = sync_co_candidates.apply(
                args=[election.pk, "primary", "fp123", "co_sos:candidate_page_fingerprint:primary"]
            ).get()

        # Primary with D Governor + R Governor → 1 canonical Race (party-agnostic key), 2 candidates
        assert result["created"] >= 2
        assert Race.objects.filter(election=election).count() == 1
        assert Candidate.objects.filter(race__election=election).count() == 2
        mock_cache.set.assert_called_once()

    def test_handles_missing_election_gracefully(self):
        from integrations.co_sos.tasks import sync_co_candidates

        result = sync_co_candidates.apply(
            args=[999999, "primary", "fp", "cache_key"]
        ).get()

        assert result is None


# ---------------------------------------------------------------------------
# Integration tests — ingest service routing (real DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_co_elections_routes_through_ingest_service():
    """Each CO election lands as a canonical Election with contributing_sources=['co_sos']."""
    from aggregation.models import SourcePrecedence
    from elections.models import ElectionSourceLink
    from integrations.co_sos.tasks import sync_co_elections

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    with (
        patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
        patch("integrations.co_sos.tasks.cache") as mock_cache,
        patch("integrations.co_sos.tasks.sync_co_candidates"),
        patch("integrations.co_sos.tasks._current_even_year", return_value=2026),
    ):
        MockClient.return_value.get_candidate_page_fingerprint.return_value = "fp123"
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        sync_co_elections.run()

    link = ElectionSourceLink.objects.filter(source="co_sos", source_id="co_sos_2026_primary").first()
    assert link is not None
    assert "co_sos" in link.election.contributing_sources
    assert link.election.canonical_key.startswith("CO:")


@pytest.mark.django_db
def test_sync_co_candidates_routes_through_ingest_service():
    """sync_co_candidates writes canonical Race + Candidate via ingest."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.co_sos.tasks import sync_co_candidates

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    e = Election.objects.create(
        name="2026 Colorado Primary Election",
        election_date=date(2026, 6, 30),
        election_type="primary",
        jurisdiction_level="state",
        state="CO",
        canonical_key="CO:primary:2026-06-30:state",
        contributing_sources=["co_sos"],
    )

    html = """
    <html><body><table>
      <tr>
        <th scope='col'>Candidate name</th>
        <th scope='col'>Office</th>
        <th scope='col'>District</th>
        <th scope='col'>Party</th>
        <th scope='col'>Write in?</th>
      </tr>
      <tr>
        <td>Alice Johnson</td><td>Governor</td><td>Statewide</td><td>Democratic Party</td><td>N</td>
      </tr>
    </table></body></html>
    """

    with (
        patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
        patch("integrations.co_sos.tasks.cache") as mock_cache,
    ):
        MockClient.return_value.fetch_candidate_html.return_value = html
        mock_cache.set = MagicMock()
        sync_co_candidates.run(e.pk, "primary", "fp123", "co_sos:fingerprint:primary")

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert "co_sos" in race.contributing_sources
    cands = list(Candidate.objects.filter(race=race))
    assert len(cands) == 1
    assert cands[0].name == "Alice Johnson"
