from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from integrations.or_sos.parsers import (
    ballot_return_payload,
    latest_ballot_returns_by_election,
    parse_ballot_count_history,
)
from integrations.or_sos.tasks import sync_or_turnout
from ops.models import SyncLog

_SOCRATA_ROWS = [
    {
        "election": "November 5, 2024 General Election",
        "date": "2024-11-04T00:00:00.000",
        "number_of_ballots_returned": "314110",
        "daily_return_as_of_total": "0.102",
        "daily_return_as_of_total_1": "0.147",
        "cumulative_number_of_ballots": "1738820",
        "cumulative_return_as_of_total": "0.565",
        "cumulative_return_as_of_total_1": "0.813",
    },
    {
        "election": "November 5, 2024 General Election",
        "date": "2024-11-05T00:00:00.000",
        "number_of_ballots_returned": "398793",
        "daily_return_as_of_total": "0.13",
        "daily_return_as_of_total_1": "0.187",
        "cumulative_number_of_ballots": "2137613",
        "cumulative_return_as_of_total": "0.694",
        "cumulative_return_as_of_total_1": "1",
    },
]


def test_parse_ballot_count_history_rows():
    records = parse_ballot_count_history(_SOCRATA_ROWS)

    assert len(records) == 2
    assert records[0].election_date == datetime.date(2024, 11, 5)
    assert records[0].count_date == datetime.date(2024, 11, 4)
    assert records[0].daily_ballots_returned == 314110
    assert records[0].cumulative_return_pct_of_total_return == 0.813


def test_latest_ballot_returns_by_election_keeps_latest_count_date():
    records = parse_ballot_count_history(_SOCRATA_ROWS)
    latest = latest_ballot_returns_by_election(records)

    record = latest[datetime.date(2024, 11, 5)]
    assert record.count_date == datetime.date(2024, 11, 5)
    assert record.cumulative_ballots_returned == 2137613


def test_ballot_return_payload_is_json_ready():
    record = latest_ballot_returns_by_election(parse_ballot_count_history(_SOCRATA_ROWS))[datetime.date(2024, 11, 5)]
    payload = ballot_return_payload(record, "https://data.oregon.gov/resource/rxzj-n3di.json")

    assert payload["election_date"] == "2024-11-05"
    assert payload["count_date"] == "2024-11-05"
    assert payload["source_url"] == "https://data.oregon.gov/resource/rxzj-n3di.json"


def test_sync_or_turnout_updates_matching_election_metadata():
    sync_log = MagicMock()
    election = MagicMock()
    election.election_date = datetime.date(2024, 11, 5)
    election.source_metadata = {"existing": "value"}

    with patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("integrations.or_sos.tasks.Election.objects.filter", return_value=[election]):
        MockClient.return_value.fetch_ballot_count_history.return_value = (
            _SOCRATA_ROWS,
            "https://data.oregon.gov/resource/rxzj-n3di.json?$limit=5000",
        )

        result = sync_or_turnout.run()

    assert result == {"updated": 1, "parsed": 2, "latest_elections": 1}
    assert election.source_metadata["existing"] == "value"
    assert election.source_metadata["or_sos_ballot_return"]["cumulative_ballots_returned"] == 2137613
    election.save.assert_called_once_with(update_fields=["source_metadata"])
    assert sync_log.status == SyncLog.Status.COMPLETED
