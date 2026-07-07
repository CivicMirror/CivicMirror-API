"""Tests for California SOS results adapter."""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.ca import CaliforniaAdapter, _parse_reporting_pct

SAMPLE_CONTEST_JSON = [
    {
        "raceTitle": "Governor - Statewide Results",
        "Reporting": "100.0% (27,188 of 27,188) precincts reporting",
        "candidates": [
            {"Name": "Alice Smith", "Party": "Dem", "Votes": "1,500,000", "Percent": "55.20", "incumbent": True, "W": 1},
            {"Name": "Bob Jones", "Party": "Rep", "Votes": "1,200,000", "Percent": "44.80", "incumbent": False, "W": 0},
        ],
    }
]


class TestParseReportingPct:
    def test_parses_full(self):
        assert _parse_reporting_pct("100.0% (27,188 of 27,188) precincts reporting") == 100.0

    def test_parses_partial(self):
        assert _parse_reporting_pct("55.3% (15,000 of 27,188) precincts reporting") == 55.3

    def test_returns_zero_on_empty(self):
        assert _parse_reporting_pct("") == 0.0

    def test_returns_zero_on_no_match(self):
        assert _parse_reporting_pct("not a percent") == 0.0


class TestCaliforniaAdapter:
    def test_state_is_ca(self):
        assert CaliforniaAdapter.state == "CA"

    def test_returns_empty_when_no_election(self, db):
        adapter = CaliforniaAdapter()
        from datetime import date
        result = adapter.fetch_results(date(2026, 11, 3), 99999)
        assert result.rows == []
        assert result.mapping_confidence == "none"

    def test_returns_result_rows_from_api(self, db):
        from datetime import date

        from elections.models import Election, Race

        election = Election.objects.create(
            source_id="ca_sos_2026_general",
            name="2026 California General Election",
            election_date=date(2026, 11, 3),
            jurisdiction_level="state",
            state="CA",
            status="results_pending",
        )
        Race.objects.create(
            election=election,
            office_title="Governor - Statewide Results",
            canonical_key="ca_sos:ca_sos_2026_general:governor",
            race_type="candidate",
            jurisdiction="California",
            geography_scope="statewide",
            certification_status="results_pending",
            source="ca_sos",
            race_status="active",
            vote_method="single_choice",
            max_selections=1,
            source_metadata={"ca_endpoint": "/returns/governor"},
        )

        adapter = CaliforniaAdapter()

        with (
            patch("results.adapters.ca.requests.get") as mock_get,
            patch("results.adapters.ca.cache") as mock_cache,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'[{"raceTitle":"Governor","Reporting":"100.0%","candidates":[{"Name":"Alice Smith","Party":"Dem","Votes":"1500000","Percent":"55.2","incumbent":true,"W":1}]}]'
            mock_resp.json.return_value = SAMPLE_CONTEST_JSON
            mock_get.return_value = mock_resp
            mock_cache.get.return_value = None  # Cache miss — process results

            result = adapter.fetch_results(date(2026, 11, 3), election.pk)

        assert len(result.rows) >= 1
        alice = next((r for r in result.rows if r.candidate_name == "Alice Smith"), None)
        assert alice is not None
        assert alice.result_type == "unofficial"
        assert alice.office_title == "Governor - Statewide Results"

    def test_skips_race_without_ca_endpoint(self, db):
        from datetime import date

        from elections.models import Election, Race

        election = Election.objects.create(
            source_id="ca_sos_test_no_endpoint",
            name="CA Test Election",
            election_date=date(2026, 11, 3),
            jurisdiction_level="state",
            state="CA",
            status="results_pending",
        )
        Race.objects.create(
            election=election,
            office_title="Governor",
            canonical_key="ca_sos:test:governor:no_endpoint",
            race_type="candidate",
            jurisdiction="California",
            geography_scope="statewide",
            certification_status="results_pending",
            source="ca_sos",
            race_status="active",
            vote_method="single_choice",
            max_selections=1,
            source_metadata={},  # No ca_endpoint key
        )

        adapter = CaliforniaAdapter()
        with patch("results.adapters.ca.requests.get") as mock_get:
            from datetime import date
            result = adapter.fetch_results(date(2026, 11, 3), election.pk)
            mock_get.assert_not_called()

        assert result.rows == []

    def test_registered_in_registry(self):
        from results.adapters.registry import get_adapter
        adapter_cls = get_adapter("CA")
        assert adapter_cls is CaliforniaAdapter
