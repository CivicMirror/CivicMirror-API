from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from elections.models import Election
from integrations.or_sos.mappers import map_election
from integrations.or_sos.parsers import OrElectionInfo, parse_election_page, parse_election_text
from integrations.or_sos.tasks import sync_or_elections
from ops.models import SyncLog

_ELECTION_HTML = """
<html><body>
  <h1>November 3, 2026 General Election</h1>
  <p>May 19, 2026 Primary Election</p>
</body></html>
"""


def test_parse_election_page_extracts_dated_elections():
    elections = parse_election_page(_ELECTION_HTML, source_url="https://example.test/current")

    assert elections == [
        OrElectionInfo(
            name="Oregon General Election",
            election_date="November 3, 2026",
            election_type="general",
            source_url="https://example.test/current",
        ),
        OrElectionInfo(
            name="Oregon Primary Election",
            election_date="May 19, 2026",
            election_type="primary",
            source_url="https://example.test/current",
        ),
    ]


def test_parse_election_text_deduplicates_same_date_and_type():
    elections = parse_election_text("November 3, 2026 General Election\nGeneral Election November 3, 2026")

    assert len(elections) == 1
    assert elections[0].election_type == "general"


def test_parse_election_text_handles_split_heading_and_date():
    elections = parse_election_text("General Election\nOregon will hold a statewide general election on\nNovember 3, 2026.")

    assert elections == [
        OrElectionInfo(
            name="Oregon General Election",
            election_date="November 3, 2026",
            election_type="general",
        )
    ]


def test_parse_election_text_ignores_deadlines_after_paragraph_mentions():
    elections = parse_election_text(
        "Major parties nominate their party candidates at the Primary Election.\n"
        "Important Election Dates\n"
        "April 28, 2026\n"
        "June 25, 2026\n"
        "Final election results certified."
    )

    assert elections == []


def test_map_election_sets_identity_fields():
    mapped = map_election(
        OrElectionInfo(
            name="Oregon General Election",
            election_date="November 3, 2026",
            election_type="general",
            source_url="https://example.test/current",
        )
    )

    assert mapped["source_id"] == "or_sos_2026_general_20261103"
    assert mapped["election_date"] == datetime.date(2026, 11, 3)
    assert mapped["election_type"] == Election.ElectionType.GENERAL
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["state"] == "OR"
    assert mapped["source_metadata"]["source_url"] == "https://example.test/current"
    assert mapped["source_metadata"]["or_sos_orestar_election_id"] == "1453"


def test_sync_or_elections_upserts_and_queues_general_race_skeleton():
    sync_log = MagicMock()
    general_election = MagicMock(pk=100)
    primary_election = MagicMock(pk=101)

    with patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("aggregation.ingest.ingest_election") as mock_ingest, \
         patch("integrations.or_sos.tasks.sync_or_race_skeleton") as mock_race_task, \
         patch("integrations.or_sos.tasks.sync_or_candidates") as mock_candidate_task, \
         patch("integrations.or_sos.tasks.sync_or_local_measures") as mock_measure_task:
        MockClient.return_value.fetch_page_text.side_effect = [
            (_ELECTION_HTML, "https://example.test/current"),
            (_ELECTION_HTML, "https://example.test/dates"),
        ]
        mock_ingest.side_effect = [(general_election, True), (primary_election, False)]

        result = sync_or_elections.run()

    assert result == {"created": 1, "updated": 1, "skipped": 2, "queued": 3}
    assert mock_ingest.call_count == 2
    assert mock_race_task.apply_async.call_count == 1
    assert mock_race_task.apply_async.call_args.kwargs["args"] == [general_election.pk]
    assert mock_candidate_task.apply_async.call_count == 1
    assert mock_candidate_task.apply_async.call_args.kwargs["args"] == [general_election.pk, "1453", 2026]
    assert mock_measure_task.apply_async.call_count == 1
    assert mock_measure_task.apply_async.call_args.kwargs["args"] == [primary_election.pk, "1451", 2026]
    assert sync_log.status == SyncLog.Status.COMPLETED
