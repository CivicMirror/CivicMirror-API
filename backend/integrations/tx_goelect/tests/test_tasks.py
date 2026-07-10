"""Unit tests for TX GoElect Celery tasks. DB and Celery are fully mocked."""
from unittest.mock import MagicMock, call, patch

import pytest

from integrations.tx_goelect.tasks import sync_tx_elections, sync_tx_races


def _mock_log():
    log = MagicMock()
    log.Status.STARTED = "started"
    log.Status.COMPLETED = "completed"
    log.Status.FAILED = "failed"
    log.Status.COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    return log


def _run_sync_tx_elections_with_one_online_election(
    *, ingest_election_return, extra_patches=()
):
    """
    Shared scaffolding for the single-online-election, no-probe-hits case.
    Returns (result, mock_subtask) so callers can assert on either.
    """
    constants = {
        "electionInfo": {
            "2026": {
                "RU": {"58315": {"O": "Y", "N": "2026 REPUBLICAN PRIMARY RUNOFF"}}
            }
        }
    }
    home = {"ElecDate": "05262026", "CountiesReporting": {"CR": 254, "CT": 254}}

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=ingest_election_return):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.get_election_data.return_value = {"version": 70, "home": home, "lookups": {}}
        client.probe_election.return_value = False  # no probe hits
        # Watermark past probe range so probe loop doesn't run
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_elections()

    return result, mock_subtask


# ---------------------------------------------------------------------------
# sync_tx_elections — electionConstants polling
# ---------------------------------------------------------------------------

def test_sync_tx_elections_skips_offline_elections():
    """Elections with O='N' are not ingested."""
    constants = {
        "electionInfo": {
            "2026": {
                "P": {"53813": {"O": "N", "N": "2026 REPUBLICAN PRIMARY"}}
            }
        }
    }

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask:

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.return_value = False  # no probe hits
        mock_cache.get.return_value = 58315  # watermark already past probe range
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_elections()

    assert result["created"] == 0
    mock_subtask.apply_async.assert_not_called()


def test_sync_tx_elections_ingests_online_election():
    """Elections with O='Y' → ingest_election called, sync_tx_races queued."""
    mock_election = MagicMock()
    mock_election.pk = 42

    result, mock_subtask = _run_sync_tx_elections_with_one_online_election(
        ingest_election_return=(mock_election, True),
    )

    assert result["created"] == 1
    mock_subtask.apply_async.assert_called_once()


def test_race_syncs_queued_only_after_all_discovery_done():
    """
    sync_tx_races must never be queued while sync_tx_elections still has its
    own DB writes or network calls left to make. Queuing inline during
    discovery let a race sync start executing concurrently with the parent's
    remaining work, and that overlap is what pushed TX's largest primaries
    past sync_tx_races's soft time limit every night from 2026-07-01 through
    2026-07-08. Verified here by recording call order across both mocks:
    every ingest_election call must precede every apply_async call.
    """
    constants = {
        "electionInfo": {
            "2026": {
                "P": {"53814": {"O": "Y", "N": "2026 DEMOCRATIC PRIMARY"}},
                "RU": {"58315": {"O": "Y", "N": "2026 DEMOCRATIC PRIMARY RUNOFF"}},
            }
        }
    }
    home = {"ElecDate": "05262026", "CountiesReporting": {"CR": 254, "CT": 254}}
    mock_election = MagicMock()
    mock_election.pk = 42

    call_order = []

    def fake_ingest_election(**kwargs):
        call_order.append("ingest")
        return (mock_election, True)

    def fake_apply_async(**kwargs):
        call_order.append("queue")

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", side_effect=fake_ingest_election):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.get_election_data.return_value = {"version": 70, "home": home, "lookups": {}}
        client.probe_election.return_value = False
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()
        mock_subtask.apply_async.side_effect = fake_apply_async

        sync_tx_elections()

    assert call_order == ["ingest", "ingest", "queue", "queue"], call_order

    # And each queued call is still staggered — first at countdown=0 (safe now
    # that it only fires after discovery is fully done), each next +5s.
    countdowns = [c.kwargs["countdown"] for c in mock_subtask.apply_async.call_args_list]
    assert countdowns == [0, 5]


# ---------------------------------------------------------------------------
# sync_tx_elections — sequential ID probe
# ---------------------------------------------------------------------------

def test_probe_stops_after_50_consecutive_misses():
    """50 misses → probe stops; watermark updated to last probed ID."""
    constants = {"electionInfo": {}}  # no elections in constants

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.return_value = False
        # Watermark at 58315, all probes miss
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # probe_election called exactly 50 times (one per miss before stop)
    assert client.probe_election.call_count == 50
    # watermark set to 58315 + 50
    mock_cache.set.assert_called_with(
        "tx_goelect:probe_watermark", 58315 + 50, timeout=None
    )


def test_probe_ingests_hit_then_continues():
    """A hit resets the miss counter; scan continues after the hit."""
    constants = {"electionInfo": {}}

    mock_election = MagicMock()
    mock_election.pk = 10

    def probe_side_effect(eid):
        return eid == 58316  # only ID 58316 is live

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.side_effect = probe_side_effect
        client.get_election_data.return_value = {
            "version": 1,
            "home": {"ElecDate": "11032026", "CountiesReporting": {"CR": 0, "CT": 254}},
            "lookups": {},
        }
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # 58316 hit → ingested
    mock_subtask.apply_async.assert_called_once()
    # Probe continued past 58316 (50 more misses)
    assert client.probe_election.call_count == 51  # 1 hit + 50 misses


def test_probe_skips_non_ge_hits():
    """A probed election that is not GE+2026-11-03 is ingested but not treated as target general."""
    constants = {"electionInfo": {}}

    mock_election = MagicMock()
    mock_election.pk = 20

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"), \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)) as mock_ie:

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.side_effect = lambda eid: eid == 58316
        client.get_election_data.return_value = {
            "version": 1,
            # Special election, not GE
            "home": {"ElecDate": "07142026", "CountiesReporting": {"CR": 0, "CT": 1}},
            "lookups": {},
        }
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # Still ingested — but metadata will have is_target_general_2026=False
    mock_ie.assert_called_once()
    fields = mock_ie.call_args[1]["fields"]
    assert fields["source_metadata"]["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# sync_tx_races
# ---------------------------------------------------------------------------

def test_sync_tx_races_upserts_candidate_race():
    """Candidate office → ingest_race + ingest_candidate called."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"tx_election_id": 56181}

    mock_race = MagicMock()
    mock_race.pk = 5
    mock_cand = MagicMock()

    data = {
        "lookups": {
            "Office": [{"ID": 5031, "ON": "STATE SENATOR, DISTRICT 4", "SSO": 4, "OT": 510}],
            "OfficeType": [{"ID": 510, "OT": "DISTRICT OFFICES"}],
            "Candidates": [{"ID": 36388, "BN": "BRETT W. LIGON"}],
        },
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "C": [{"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05}]
                }
            ]
        },
    }

    with patch("integrations.tx_goelect.tasks.Election") as MockElection, \
         patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockClient.return_value.get_election_data.return_value = data
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_races(1, 56181)

    mock_ir.assert_called_once()
    assert mock_ir.call_args[1]["identity"]["office_title"] == "STATE SENATOR, DISTRICT 4"
    mock_ic.assert_called_once()
    assert result["races"]["created"] == 1
    assert result["candidates"]["created"] == 1


def test_sync_tx_races_candidates_scoped_to_office():
    """Candidates from office B must not appear on office A's race (fan-out regression)."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"tx_election_id": 56181}

    mock_race_a = MagicMock()
    mock_race_a.pk = 10
    mock_race_b = MagicMock()
    mock_race_b.pk = 20
    mock_cand = MagicMock()

    # Two offices; each has one unique candidate.
    data = {
        "lookups": {
            "Office": [
                {"ID": 1001, "ON": "GOVERNOR", "SSO": 1, "OT": 100},
                {"ID": 1002, "ON": "LIEUTENANT GOVERNOR", "SSO": 2, "OT": 100},
            ],
            "OfficeType": [{"ID": 100, "OT": "STATEWIDE OFFICES"}],
        },
        "office_summary": {
            "OS": [
                {
                    "OID": 1001,
                    "C": [{"ID": 11, "BN": "ALICE FOR GOV", "P": "DEM", "V": 100, "PE": 60.0}],
                },
                {
                    "OID": 1002,
                    "C": [{"ID": 22, "BN": "BOB FOR LT GOV", "P": "REP", "V": 80, "PE": 55.0}],
                },
            ]
        },
    }

    race_call_order = []

    def fake_ingest_race(**kwargs):
        title = kwargs["identity"]["office_title"]
        if title == "GOVERNOR":
            race_call_order.append("gov")
            return (mock_race_a, True)
        race_call_order.append("ltgov")
        return (mock_race_b, True)

    candidate_calls_by_race: dict[int, list[str]] = {}

    def fake_ingest_candidate(*, race, source, name, party, fields):
        candidate_calls_by_race.setdefault(race.pk, []).append(name)
        return (mock_cand, True)

    with patch("integrations.tx_goelect.tasks.Election") as MockElection, \
         patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("aggregation.ingest.ingest_race", side_effect=fake_ingest_race), \
         patch("aggregation.ingest.ingest_candidate", side_effect=fake_ingest_candidate):

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockClient.return_value.get_election_data.return_value = data
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_races(1, 56181)

    # Each race gets exactly one candidate — its own.
    assert candidate_calls_by_race.get(mock_race_a.pk) == ["ALICE FOR GOV"], (
        f"Governor race got unexpected candidates: {candidate_calls_by_race.get(mock_race_a.pk)}"
    )
    assert candidate_calls_by_race.get(mock_race_b.pk) == ["BOB FOR LT GOV"], (
        f"Lt. Gov race got unexpected candidates: {candidate_calls_by_race.get(mock_race_b.pk)}"
    )
    assert result["candidates"]["created"] == 2


def test_sync_tx_races_missing_election_returns_early():
    with patch("integrations.tx_goelect.tasks.Election") as MockElection:
        MockElection.objects.get.side_effect = Exception("DoesNotExist")
        MockElection.DoesNotExist = Exception
        result = sync_tx_races(999, 56181)

    assert result is None


def test_sync_tx_races_time_limit_covers_largest_primaries():
    """
    TX's largest statewide primaries (~1300 offices / ~2000 candidates,
    measured against the live API 2026-07-08) took ~100s to ingest under
    uncontended conditions but repeatedly hit the previous 300s soft limit
    under DB lock contention, failing outright every night from 2026-07-01
    through 2026-07-08. 300s doesn't leave enough headroom above the
    uncontended baseline to absorb that contention.
    """
    assert sync_tx_races.soft_time_limit >= 600
    assert sync_tx_races.time_limit > sync_tx_races.soft_time_limit
