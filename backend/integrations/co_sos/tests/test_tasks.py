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
        from elections.models import Election
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
        from elections.models import ElectionSourceLink
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
        from elections.models import Candidate, Race
        from integrations.co_sos.tasks import sync_co_candidates

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

        assert result["created"] >= 3  # 2 races + 2 candidates
        assert Race.objects.filter(election=election).count() == 2
        assert Candidate.objects.filter(race__election=election).count() == 2
        mock_cache.set.assert_called_once()

    def test_handles_missing_election_gracefully(self):
        from integrations.co_sos.tasks import sync_co_candidates

        result = sync_co_candidates.apply(
            args=[999999, "primary", "fp", "cache_key"]
        ).get()

        assert result is None
