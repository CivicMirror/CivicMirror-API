import datetime
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from elections.models import Election, ElectionSourceLink, Race

# NOTE on the tests below that use --group-by jurisdiction for MA fixtures
# (Task 2, issue #187): they predate --group-by-compound (Task 8) and were
# written to exercise the split/reparent/dedup *mechanism*, not MA's specific
# grouping-key convergence with ma_sos's live contest_group. jurisdiction
# alone still correctly separates "6th Essex" from "3rd Bristol" in these
# fixtures, so they're left as plain --group-by jurisdiction mechanism tests.
# The production-recommended MA invocation is --group-by-compound
# office_title,jurisdiction (see the convergence test at the bottom of this
# file) — that property is proven there, not by changing these.


@pytest.mark.django_db
def test_repair_splits_ma_6th_essex_3rd_bristol_collision():
    """Reproduces production Election id 2158 (issue #187): 6th Essex
    special general + 3rd Bristol special primary collapsed onto one
    Election because contest_group didn't exist yet."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="2025 MA State Representative 3rd Bristol Republican",
    )
    ElectionSourceLink.objects.create(election=collided, source="ma_sos", source_id="ma_sos:171341")
    essex = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    bristol_d = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-d",
    )
    bristol_r = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-r",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex.refresh_from_db()
    bristol_d.refresh_from_db()
    bristol_r.refresh_from_db()

    assert essex.election_id != bristol_d.election_id
    assert bristol_d.election_id == bristol_r.election_id
    assert not Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|6th essex"
    ).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|3rd bristol"
    ).exists()


@pytest.mark.django_db
def test_repair_dry_run_makes_no_changes():
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction")  # no --yes

    assert Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.count() == 1


@pytest.mark.django_db
def test_repair_duplicates_source_link_to_every_matching_split_child():
    """Finding #1 (issue #187 follow-up): the original Election's
    ElectionSourceLink must not simply be deleted. When both split groups
    are built from races sharing the same source (as in MA's real 6th
    Essex / 3rd Bristol collision), the link is duplicated onto both split
    children rather than silently dropped, so neither loses provenance."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="2025 MA State Representative 3rd Bristol Republican",
    )
    ElectionSourceLink.objects.create(
        election=collided, source="ma_sos", source_id="ma_sos:171341",
        results_url="https://electionstats.state.ma.us/some/path",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol-d",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|6th essex")
    bristol_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|3rd bristol")

    assert ElectionSourceLink.objects.filter(election=essex_election, source="ma_sos").exists()
    assert ElectionSourceLink.objects.filter(election=bristol_election, source="ma_sos").exists()
    assert not ElectionSourceLink.objects.filter(election_id=collided.pk).exists()


@pytest.mark.django_db
def test_repair_derives_contributing_sources_per_split_group():
    """Finding #2 (issue #187 follow-up): contributing_sources on each split
    child must reflect only the sources actually backing that child's own
    races, not the full contributing_sources list of the original collided
    Election."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
        contributing_sources=["ma_sos", "civic_api"],
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol-d",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.CIVIC_API, canonical_key="race-bristol-r",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|6th essex")
    bristol_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|3rd bristol")

    assert essex_election.contributing_sources == ["ma_sos"]
    assert bristol_election.contributing_sources == ["civic_api", "ma_sos"]


@pytest.mark.django_db
def test_repair_is_idempotent():
    """A second run after a successful repair finds nothing left to split."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)
    count_after_first_run = Election.objects.count()
    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    assert Election.objects.count() == count_after_first_run


# ---------------------------------------------------------------------------
# Task 8 (issue #187 follow-up): CLI grouping-mode selection
# ---------------------------------------------------------------------------

def test_repair_requires_exactly_one_group_by_mode():
    """No mode supplied at all must be rejected by argparse."""
    from io import StringIO

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("repair_collided_elections", state="MA", stderr=StringIO())


def test_repair_rejects_multiple_group_by_modes():
    """Supplying more than one --group-by* mode must be rejected — they are
    mutually exclusive (argparse add_mutually_exclusive_group)."""
    from io import StringIO

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command(
            "repair_collided_elections", state="MA",
            group_by="jurisdiction", group_by_metadata="vrems_election_id",
            stderr=StringIO(),
        )


def test_repair_group_by_compound_rejects_wrong_field_count():
    """--group-by-compound must receive exactly two comma-separated fields."""
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command(
            "repair_collided_elections", state="MA",
            group_by_compound="office_title", yes=True,
        )


# ---------------------------------------------------------------------------
# Task 8 (issue #187 follow-up): grouping-key convergence with live adapters
#
# The whole point of this task: the repair command's new grouping-key formula
# must produce the exact same canonical_key that each state's live adapter
# computes for contest_group at ingest time. Each test below proves this by
# (1) reproducing a pre-fix collided Election exactly as it would exist in
# production and repairing it with the new grouping mode, then (2) running
# the REAL (unmocked) adapter sync task — only its HTTP client is mocked —
# against equivalent synthetic source data, letting it hit the real
# aggregation.ingest.ingest_election / election_canonical_key. If the two
# code paths' canonical_keys don't match byte-for-byte, the live sync would
# create a second, duplicate Election instead of updating the repaired one;
# these tests assert that does NOT happen.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_repair_group_by_compound_converges_with_ma_sos_live_contest_group():
    """MA convergence proof. ma_sos's live contest_group is computed at
    integrations/ma_sos/tasks.py:159 as
    `identity["contest_group"] = f"{office}:{district}".strip().lower()`,
    where office/district come straight from electionstats discovery and are
    written onto Race.office_title / Race.jurisdiction by
    integrations/ma_sos/mappers.py:277-279 (office_title=office,
    jurisdiction=district). --group-by-compound office_title,jurisdiction
    must reconstruct that exact string from the persisted Race fields."""
    # --- reproduce the pre-fix collided production row (mirrors production
    # Election id 2158) and repair it with the new compound mode ---
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol",
    )

    call_command(
        "repair_collided_elections", state="MA",
        group_by_compound="office_title,jurisdiction", yes=True,
    )
    repaired_keys = set(
        Election.objects.filter(
            state="MA", election_type="special", election_date=datetime.date(2025, 5, 13),
        ).values_list("canonical_key", flat=True)
    )
    assert len(repaired_keys) == 2, "fixture setup did not actually split into two rows"

    # --- run the REAL (unmocked) sync_ma_elections against equivalent
    # discovery data for the same two contests; only MaSosClient is mocked ---
    from integrations.ma_sos.tasks import sync_ma_elections

    mock_client = MagicMock()
    mock_client.get_ocpf_schedule.return_value = {"generalElectionDate": "", "primaryElectionDate": ""}

    def fake_get_election_ids(year, stage):
        if year == 2025 and stage == "General":
            return [{
                "election_id": 171339, "office": "State Representative",
                "district": "6th Essex", "stage": "General", "year": 2025,
            }]
        if year == 2025 and stage == "Republican":
            return [{
                "election_id": 171341, "office": "State Representative",
                "district": "3rd Bristol", "stage": "Republican", "year": 2025,
            }]
        return []

    mock_client.get_election_ids.side_effect = fake_get_election_ids
    mock_client.get_ballot_question_ids.return_value = []
    mock_client.get_election_detail.side_effect = lambda eid: {
        171339: {"election_id": 171339, "date": "2025-05-13", "is_special": True, "year": 2025},
        171341: {"election_id": 171341, "date": "2025-05-13", "is_special": True, "year": 2025},
    }[eid]

    with patch("integrations.ma_sos.tasks.MaSosClient", return_value=mock_client), \
         patch("integrations.ma_sos.tasks.sync_ma_races"), \
         patch("integrations.ma_sos.tasks.sync_ma_ballot_question"), \
         patch("integrations.ma_sos.tasks.date") as mock_date:
        mock_date.today.return_value = datetime.date(2025, 12, 1)
        sync_ma_elections.run()

    live_keys = set(
        Election.objects.filter(
            state="MA", election_type="special", election_date=datetime.date(2025, 5, 13),
        ).values_list("canonical_key", flat=True)
    )

    # If the grouping keys didn't converge, this would be 4 rows (2 repaired
    # + 2 new duplicates from the live sync) instead of the same 2.
    assert live_keys == repaired_keys


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_repair_group_by_metadata_converges_with_sc_vrems_live_contest_group(MockClient):
    """SC convergence proof. sc_vrems's live contest_group is computed at
    integrations/sc_vrems/tasks.py:62 as
    `identity["contest_group"] = str(vrems_election.get("electionId", "")).lower()`,
    and that same electionId is what Stage 2 (sync_sc_races) writes onto
    Race.source_metadata["vrems_election_id"] (tasks.py:194). --group-by-metadata
    vrems_election_id must reconstruct that exact string from the persisted
    Race metadata."""
    collided = Election.objects.create(
        state="SC", election_type="special",
        election_date=datetime.date(2026, 6, 23),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="SC:special:2026-06-23:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="City Council", jurisdiction="Johnsonville",
        geography_scope="local", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.SC_VREMS, canonical_key="race-johnsonville",
        source_metadata={"vrems_election_id": "22744"},
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="School Board District 1", jurisdiction="Lexington",
        geography_scope="local", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.SC_VREMS, canonical_key="race-lexington",
        source_metadata={"vrems_election_id": "22746"},
    )

    call_command(
        "repair_collided_elections", state="SC",
        group_by_metadata="vrems_election_id", yes=True,
    )
    repaired_keys = set(
        Election.objects.filter(
            state="SC", election_type="special", election_date=datetime.date(2026, 6, 23),
        ).values_list("canonical_key", flat=True)
    )
    assert len(repaired_keys) == 2, "fixture setup did not actually split into two rows"

    MockClient.return_value.get_all_elections.return_value = [
        {
            "electionId": "22744",
            "electionName": "City of Johnsonville Special Election",
            "displayName": "6/23/2026 City of Johnsonville Special Election",
            "electionDate": "2026-06-23T00:00:00",
            "filingPeriodBeginDate": "2020-03-16T12:00:00",
            "electionType": "Special",
        },
        {
            "electionId": "22746",
            "electionName": "Lexington School Board District 1 Special Election",
            "displayName": "6/23/2026 Lexington School Board District 1 Special Election",
            "electionDate": "2026-06-23T00:00:00",
            "filingPeriodBeginDate": "2020-03-16T12:00:00",
            "electionType": "Special",
        },
    ]
    with patch("integrations.sc_vrems.tasks.sync_sc_races"):
        from integrations.sc_vrems.tasks import sync_sc_elections
        sync_sc_elections()

    live_keys = set(
        Election.objects.filter(
            state="SC", election_type="special", election_date=datetime.date(2026, 6, 23),
        ).values_list("canonical_key", flat=True)
    )

    assert live_keys == repaired_keys


@pytest.mark.django_db
def test_repair_group_by_metadata_converges_with_tx_goelect_live_contest_group():
    """TX convergence proof. tx_goelect's live contest_group is computed at
    integrations/tx_goelect/tasks.py:102 as
    `identity["contest_group"] = str(election_id).lower()`, and that same
    election_id is what Stage 2's map_race writes onto
    Race.source_metadata["tx_election_id"] (integrations/tx_goelect/mappers.py:126).
    --group-by-metadata tx_election_id must reconstruct that exact string
    from the persisted Race metadata (including the int -> str coercion,
    since tx_election_id is stored as an int, not a str)."""
    collided = Election.objects.create(
        state="TX", election_type="special",
        election_date=datetime.date(2025, 11, 4),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="TX:special:2025-11-04:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="U.S. Representative District 18", jurisdiction="District 18",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.TX_GOELECT, canonical_key="race-cd18",
        source_metadata={"tx_election_id": 11090},  # int, matching mappers.py:126
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Senator District 9", jurisdiction="District 9",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.TX_GOELECT, canonical_key="race-sd9",
        source_metadata={"tx_election_id": 11088},
    )

    call_command(
        "repair_collided_elections", state="TX",
        group_by_metadata="tx_election_id", yes=True,
    )
    repaired_keys = set(
        Election.objects.filter(
            state="TX", election_type="special", election_date=datetime.date(2025, 11, 4),
        ).values_list("canonical_key", flat=True)
    )
    assert len(repaired_keys) == 2, "fixture setup did not actually split into two rows"

    constants = {
        "electionInfo": {
            "2025": {
                "S": {
                    "11090": {"O": "Y", "N": "SPECIAL ELECTION CONGRESSIONAL DISTRICT 18"},
                    "11088": {"O": "Y", "N": "SPECIAL ELECTION STATE SENATE DISTRICT 9"},
                }
            }
        }
    }
    home = {"ElecDate": "11042025", "CountiesReporting": {"CR": 1, "CT": 1}}

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"):
        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.get_election_data.return_value = {"version": 1, "home": home, "lookups": {}}
        client.probe_election.return_value = False
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default

        from integrations.tx_goelect.tasks import sync_tx_elections
        sync_tx_elections.run()

    live_keys = set(
        Election.objects.filter(
            state="TX", election_type="special", election_date=datetime.date(2025, 11, 4),
        ).values_list("canonical_key", flat=True)
    )

    assert live_keys == repaired_keys


# ---------------------------------------------------------------------------
# Task 8 review, Finding #1 (Critical): a race whose grouping key resolves to
# empty must never be silently reparented onto (and then CASCADE-deleted
# with) the original collided Election. Reproduces the reviewer's own repro:
# a 2-race SC fixture where one race's source_metadata is missing the
# grouping key went from 2 races to 1 after --yes, pre-fix.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_repair_group_by_metadata_raises_on_empty_group_key_instead_of_deleting_races():
    """The reviewer's exact reproduction: a 2-race SC fixture, one race
    missing vrems_election_id entirely. Pre-fix this went 2 races -> 1 after
    --yes (the empty-key race silently reparented onto, then CASCADE-deleted
    with, the original Election). Must now raise CommandError with zero
    mutation instead."""
    collided = Election.objects.create(
        state="SC", election_type="special",
        election_date=datetime.date(2026, 6, 23),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="SC:special:2026-06-23:state",
        name="Collided",
    )
    race_with_key = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="City Council", jurisdiction="Johnsonville",
        geography_scope="local", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.SC_VREMS, canonical_key="race-johnsonville",
        source_metadata={"vrems_election_id": "22744"},
    )
    race_missing_key = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="School Board District 1", jurisdiction="Lexington",
        geography_scope="local", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.SC_VREMS, canonical_key="race-lexington",
        source_metadata={},  # vrems_election_id entirely absent — the reviewer's repro
    )

    with pytest.raises(CommandError):
        call_command(
            "repair_collided_elections", state="SC",
            group_by_metadata="vrems_election_id", yes=True,
        )

    # Zero mutation: both races and the original Election survive unchanged.
    assert Race.objects.count() == 2
    assert Election.objects.count() == 1
    assert Election.objects.filter(pk=collided.pk).exists()
    race_with_key.refresh_from_db()
    race_missing_key.refresh_from_db()
    assert race_with_key.election_id == collided.pk
    assert race_missing_key.election_id == collided.pk


@pytest.mark.django_db
def test_repair_group_by_compound_raises_on_empty_field_instead_of_silently_splitting():
    """Same guard, compound mode. Unlike --group-by-metadata, --group-by-compound's
    "f1:f2" joined format always contains the ':' separator, so a race with one
    empty constituent field never produces a literal "" joined key — the
    CASCADE-delete mechanism from the metadata-mode test above can't reproduce
    verbatim here. The guard instead checks each constituent field individually
    (see _resolve_grouping's is_empty_fn), because a key built from an empty
    field can't converge with the live adapter's own contest_group either (the
    module docstring's --group-by-compound precondition) — refusing here is
    still required, just for a related-but-distinct reason than the metadata
    case."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    race_with_district = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    race_empty_district = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="",  # empty compound field
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-empty-district",
    )

    with pytest.raises(CommandError):
        call_command(
            "repair_collided_elections", state="MA",
            group_by_compound="office_title,jurisdiction", yes=True,
        )

    assert Race.objects.count() == 2
    assert Election.objects.count() == 1
    assert Election.objects.filter(pk=collided.pk).exists()
    race_with_district.refresh_from_db()
    race_empty_district.refresh_from_db()
    assert race_with_district.election_id == collided.pk
    assert race_empty_district.election_id == collided.pk


# ---------------------------------------------------------------------------
# Task 8 review, Finding #2 (Important): GA/VA must be a hard, code-level
# refusal, not just a docstring warning. Their "collided" special elections
# are legitimate single ballots (multi-jurisdiction, one public_id/enr_slug
# each), not genuine collisions — splitting them would be destructive.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_repair_refuses_ga_and_does_not_touch_the_database():
    existing = Election.objects.create(
        state="GA", election_type="special",
        election_date=datetime.date(2025, 6, 17),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="GA:special:2025-06-17:state",
        name="GA collided (legitimate multi-district ballot)",
    )
    Race.objects.create(
        election=existing, race_type=Race.RaceType.CANDIDATE,
        office_title="State House District 1", jurisdiction="District 1",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.GA_SOS, canonical_key="ga-race-1",
    )
    Race.objects.create(
        election=existing, race_type=Race.RaceType.CANDIDATE,
        office_title="State House District 2", jurisdiction="District 2",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_PENDING,
        source=Race.Source.GA_SOS, canonical_key="ga-race-2",
    )

    with pytest.raises(CommandError):
        call_command("repair_collided_elections", state="GA", group_by="jurisdiction", yes=True)

    existing.refresh_from_db()
    assert Election.objects.count() == 1
    assert Election.objects.get(pk=existing.pk).canonical_key == "GA:special:2025-06-17:state"
    assert Race.objects.count() == 2


@pytest.mark.django_db
def test_repair_refuses_va_and_does_not_touch_the_database():
    with pytest.raises(CommandError):
        call_command("repair_collided_elections", state="VA", group_by="jurisdiction", yes=True)
    assert Election.objects.count() == 0


# ---------------------------------------------------------------------------
# Task 8 review, Finding #3 (Important): --group-by-compound's dry-run
# preview must warn when a group's value contains a known default-placeholder
# literal ("statewide"), since a mapper-applied default (e.g. MA's
# jurisdiction defaulting to "Statewide" for an empty district) will not
# converge with the live adapter's own un-defaulted contest_group.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_repair_compound_dry_run_warns_on_statewide_placeholder_value(capsys):
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 9, 2),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-09-02:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex-2",
    )
    # A mapper-defaulted placeholder value, not a genuine source value — the
    # scenario Finding #3 is about (ma_sos/mappers.py:277-279 defaults
    # Race.jurisdiction to "Statewide" when the raw district is empty).
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="Governor's Council 3rd District", jurisdiction="Statewide",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-gc-statewide",
    )

    call_command(
        "repair_collided_elections", state="MA",
        group_by_compound="office_title,jurisdiction",
        no_color=True,  # avoid ANSI wrapping so a plain substring check is reliable
    )  # dry run, no --yes

    output = capsys.readouterr().out
    assert "WARNING" in output and "statewide" in output.lower()


@pytest.mark.django_db
def test_repair_compound_dry_run_does_not_warn_for_normal_districted_group(capsys):
    """No 'statewide' warning for an ordinary districted compound group —
    the warning is a targeted heuristic, not noise on every dry run."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex-3",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol-no-warning",
    )

    call_command(
        "repair_collided_elections", state="MA",
        group_by_compound="office_title,jurisdiction",
        no_color=True,
    )  # dry run, no --yes

    output = capsys.readouterr().out
    assert "WARNING" not in output
