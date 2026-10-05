"""Winner derivation rules (results/winners.py)."""
import pytest

from elections.models import Candidate, Election, Race
from results.models import OfficialResult
from results.winners import DERIVED_MARKER, Derivation, apply_derivation, derive_and_apply, derive_winners

_n = iter(range(10_000))


def _election(etype="general", state="MA"):
    return Election.objects.create(name=f"E{next(_n)}", election_date="2026-09-01", election_type=etype,
                                   jurisdiction_level="state", state=state, canonical_key=f"w:{next(_n)}",
                                   status="results_certified")


def _race(election, party="", seats=None, rtype="candidate", title="State Representative District 3"):
    kw = {}
    if seats:
        kw.update(vote_method=Race.VoteMethod.MULTI_SEAT, max_selections=seats)
    return Race.objects.create(election=election, race_type=rtype, office_title=title, jurisdiction="X",
                               geography_scope="district", source="civic_api", canonical_key=f"wr:{next(_n)}",
                               certification_status="results_certified", party=party, **kw)


def _row(race, name, votes, party="", fragment="", **kw):
    cand = Candidate.objects.get_or_create(race=race, name=name, defaults={"party": party})[0] if name else None
    return OfficialResult.objects.create(race=race, candidate=cand, vote_count=votes, jurisdiction_fragment=fragment,
                                         result_type="official", **kw)


def _winners(race):
    return sorted(OfficialResult.objects.filter(race=race, is_winner=True).values_list("candidate__name", flat=True))


@pytest.mark.django_db
def test_single_seat_general_marks_top_and_losers_false():
    race = _race(_election())
    _row(race, "Field", 2575)
    _row(race, "Quintal", 2560)
    _row(race, None, 8, is_write_in_aggregate=True)
    _row(race, "Field", 1542, fragment="Taunton")
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["Field"]
    assert OfficialResult.objects.get(race=race, candidate__name="Quintal", jurisdiction_fragment="").is_winner is False
    assert OfficialResult.objects.get(race=race, jurisdiction_fragment="Taunton").is_winner is None
    assert OfficialResult.objects.get(race=race, is_write_in_aggregate=True).is_winner is None
    race.refresh_from_db()
    assert race.source_metadata[DERIVED_MARKER] is True


@pytest.mark.django_db
def test_consolidated_primary_picks_one_winner_per_party():
    race = _race(_election("primary", "TN"))
    _row(race, "Blackburn", 311392, party="Republican")
    _row(race, "Rose", 235561, party="Republican")
    _row(race, "Green", 244277, party="Democratic")
    _row(race, "Atwater", 63289, party="Democratic")
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["Blackburn", "Green"]


@pytest.mark.django_db
def test_consolidated_primary_with_unknown_party_is_skipped():
    race = _race(_election("primary", "TN"))
    _row(race, "A", 10, party="Republican")
    _row(race, "B", 5, party="")
    assert derive_winners(race).outcome == "skipped_primary_unpartitioned"


@pytest.mark.django_db
def test_top_two_primary_state_skipped():
    race = _race(_election("primary", "WA"))
    _row(race, "A", 10, party="Republican")
    _row(race, "B", 5, party="Democratic")
    assert derive_winners(race).outcome == "skipped_top_two_primary"


@pytest.mark.django_db
def test_party_split_primary_race_is_a_single_group():
    race = _race(_election("primary", "MA"), party="Democratic")
    _row(race, "Markey", 580628, party="Democratic")
    _row(race, "Moulton", 314198, party="Democratic")
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["Markey"]


@pytest.mark.django_db
def test_multi_seat_top_n_and_tie_at_last_seat_skips():
    race = _race(_election(), seats=2)
    _row(race, "A", 30)
    _row(race, "B", 20)
    _row(race, "C", 10)
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["A", "B"]

    tied = _race(_election(), seats=2)
    _row(tied, "A", 30)
    _row(tied, "B", 20)
    _row(tied, "C", 20)
    assert derive_winners(tied).outcome == "skipped_tie"


@pytest.mark.django_db
def test_single_seat_tie_skipped():
    race = _race(_election())
    _row(race, "A", 100)
    _row(race, "B", 100)
    assert derive_winners(race).outcome == "skipped_tie"


@pytest.mark.django_db
def test_source_set_winners_are_never_touched():
    race = _race(_election())
    _row(race, "A", 10, is_winner=False)  # adapter-set, deliberately False
    _row(race, "B", 20)
    assert derive_and_apply(race) == "skipped_source_set"
    assert OfficialResult.objects.get(race=race, candidate__name="A").is_winner is False
    assert OfficialResult.objects.get(race=race, candidate__name="B").is_winner is None


@pytest.mark.django_db
@pytest.mark.parametrize("setup,outcome", [
    ("measure", "skipped_measure"),
    ("no_totals", "skipped_no_totals"),
    ("unofficial", "skipped_unofficial"),
    ("zero", "skipped_zero_votes"),
    ("rcv", "skipped_ranked_choice"),
    ("not_certified", "skipped_not_certified"),
])
def test_skip_rules(setup, outcome):
    race = _race(_election(), rtype="measure" if setup == "measure" else "candidate")
    if setup == "no_totals":
        _row(race, "A", 10, fragment="Boston")
    elif setup == "unofficial":
        row = _row(race, "A", 10)
        OfficialResult.objects.filter(pk=row.pk).update(result_type="unofficial")
    elif setup == "zero":
        _row(race, "A", 0)
        _row(race, "B", 0)
    elif setup == "rcv":
        _row(race, "A", 10, round_number=1)
    elif setup == "not_certified":
        Race.objects.filter(pk=race.pk).update(certification_status="results_pending")
        race.refresh_from_db()
        _row(race, "A", 10)
    else:
        _row(race, "A", 10)
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
def test_rederivation_after_correction_and_stale_flags_cleared_on_tie():
    race = _race(_election())
    a = _row(race, "A", 100)
    b = _row(race, "B", 90)
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["A"]

    OfficialResult.objects.filter(pk=b.pk).update(vote_count=120)  # recount flips the result
    race.refresh_from_db()
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["B"]

    OfficialResult.objects.filter(pk=a.pk).update(vote_count=120)  # now a tie
    race.refresh_from_db()
    assert derive_and_apply(race) == "skipped_tie"
    assert OfficialResult.objects.filter(race=race, is_winner__isnull=False).count() == 0
    race.refresh_from_db()
    assert DERIVED_MARKER not in race.source_metadata


def _import_rows(race, rows):
    from unittest.mock import patch

    from results.adapters.base import AdapterResult
    from results.tasks import ingest_official_results

    result = AdapterResult(rows=rows, source_url="https://example.org/results", mapping_confidence="full")
    # Only the external fetch is replaced; matching, persistence, and derivation run normally.
    with patch("results.tasks.get_adapter") as adapter:
        adapter.return_value.return_value.fetch_results.return_value = result
        ingest_official_results(race.election.state, race.election_id)
    race.refresh_from_db()


def _incoming(race, name, votes, winner=None):
    from results.adapters.base import ResultRow

    return ResultRow(candidate_name=name, option_label=None, vote_count=votes, vote_pct=None,
                     is_winner=winner, result_type="official", office_title=race.office_title)


@pytest.mark.django_db
@pytest.mark.parametrize("enabled,expected", [(False, []), (True, ["A"])])
def test_ingest_hook_respects_setting(settings, enabled, expected):
    settings.DERIVE_WINNERS_ENABLED = enabled
    race = _race(_election())
    Candidate.objects.create(race=race, name="A")
    _import_rows(race, [_incoming(race, "A", 10)])
    assert _winners(race) == expected


@pytest.mark.django_db
@pytest.mark.parametrize("enabled", [True, False])
def test_incoming_source_flags_replace_prior_derivation(settings, enabled):
    settings.DERIVE_WINNERS_ENABLED = enabled
    race = _race(_election())
    _row(race, "A", 100)
    _row(race, "B", 90)
    derive_and_apply(race)
    for _ in range(2):
        _import_rows(race, [_incoming(race, "A", 100, False), _incoming(race, "B", 90, True)])
        assert _winners(race) == ["B"]
        assert race.official_results.get(candidate__name="A").is_winner is False
        assert DERIVED_MARKER not in race.source_metadata


@pytest.mark.django_db
def test_partial_source_takeover_removes_old_derived_flags_only(settings):
    settings.DERIVE_WINNERS_ENABLED = True
    race = _race(_election())
    _row(race, "A", 100)
    _row(race, "B", 90)
    derive_and_apply(race)
    # An authoritative False alone is meaningful, even though no winner is reported.
    _import_rows(race, [_incoming(race, "B", 90, False), _incoming(race, "Unknown", 20, True)])
    assert race.certification_status == "partial_results"
    assert race.official_results.get(candidate__name="A").is_winner is None
    assert race.official_results.get(candidate__name="B").is_winner is False
    assert DERIVED_MARKER not in race.source_metadata


@pytest.mark.django_db
def test_ingest_correction_without_source_outcome_rederives_and_clears_ties(settings):
    settings.DERIVE_WINNERS_ENABLED = True
    race = _race(_election())
    _row(race, "A", 100)
    _row(race, "B", 90)
    derive_and_apply(race)
    _import_rows(race, [_incoming(race, "A", 100), _incoming(race, "B", 120)])
    assert _winners(race) == ["B"]
    _import_rows(race, [_incoming(race, "A", 120), _incoming(race, "B", 120)])
    assert not race.official_results.filter(is_winner__isnull=False).exists()
    assert DERIVED_MARKER not in race.source_metadata


@pytest.mark.django_db(transaction=True)
def test_source_takeover_and_result_writes_roll_back_together(settings):
    from unittest.mock import patch

    from results.adapters.base import AdapterResult
    from results.tasks import _process_race_results

    settings.DERIVE_WINNERS_ENABLED = True
    race = _race(_election())
    _row(race, "A", 100)
    _row(race, "B", 90)
    derive_and_apply(race)
    original = OfficialResult.objects.update_or_create

    def fail_second_write(**kwargs):
        if kwargs["candidate"].name == "B":
            raise RuntimeError("interrupted import")
        return original(**kwargs)

    result = AdapterResult([_incoming(race, "A", 80, False), _incoming(race, "B", 120, True)], "", "full")
    with patch.object(OfficialResult.objects, "update_or_create", side_effect=fail_second_write):
        with pytest.raises(RuntimeError, match="interrupted import"):
            _process_race_results(race, result, "MA")
    race.refresh_from_db()
    assert _winners(race) == ["A"]
    assert race.official_results.get(candidate__name="A").vote_count == 100
    assert race.source_metadata[DERIVED_MARKER] is True


@pytest.mark.parametrize("title,single", [
    ("State Representative", True),
    ("NC HOUSE OF REPRESENTATIVES DISTRICT 059 (REP)", True),
    ("United States House of Representatives District 1", True),
    ("Governor", True),
    ("GRAHAM COUNTY SHERIFF", True),
    ("NC DISTRICT COURT JUDGE DISTRICT 20 SEAT 01", True),
    ("State Senate", True),
    ("BURKE COUNTY BOARD OF EDUCATION AT-LARGE", False),
    ("ALAMANCE COUNTY BOARD OF COMMISSIONERS", False),
    ("CITY OF FAYETTEVILLE CITY COUNCIL DISTRICT 02", False),
    ("Governor's Council", False),
    ("NC DISTRICT COURT JUDGE DISTRICT 10", False),
    ("SOIL AND WATER CONSERVATION DISTRICT SUPERVISOR", False),
    ("TOWN OF BEULAVILLE COMMISSIONER", False),
])
def test_single_seat_office_classification(title, single):
    from results.winners import is_single_seat_office
    assert is_single_seat_office(title) is single


@pytest.mark.django_db
def test_board_race_without_recorded_seats_is_skipped():
    race = _race(_election(), title="ALAMANCE COUNTY BOARD OF COMMISSIONERS")
    _row(race, "A", 30)
    _row(race, "B", 20)
    assert derive_winners(race).outcome == "skipped_unknown_seats"
    multi = _race(_election(), title="ALAMANCE COUNTY BOARD OF COMMISSIONERS", seats=2)
    _row(multi, "A", 30)
    _row(multi, "B", 20)
    _row(multi, "C", 10)
    assert derive_winners(multi).outcome == "derived"


@pytest.mark.django_db
def test_bootstrapped_county_office_is_ambiguous_but_district_is_derived():
    sheriff = _race(_election(state="NC"), title="SHERIFF (DEM)")
    Race.objects.filter(pk=sheriff.pk).update(source="results_adapter", geography_scope="countywide")
    sheriff.refresh_from_db()
    _row(sheriff, "A", 30)
    _row(sheriff, "B", 20)
    assert derive_winners(sheriff).outcome == "skipped_ambiguous_contest"

    house = _race(_election(state="NC"), title="NC HOUSE OF REPRESENTATIVES DISTRICT 059 (REP)")
    Race.objects.filter(pk=house.pk).update(source="results_adapter", geography_scope="district")
    house.refresh_from_db()
    _row(house, "A", 30)
    _row(house, "B", 20)
    assert derive_winners(house).outcome == "derived"


@pytest.mark.django_db
@pytest.mark.parametrize("state,day,votes,outcome", [
    ("NC", "2017-05-02", (40, 35, 25), "skipped_nomination_threshold"),
    ("NC", "2017-05-02", (41, 34, 25), "derived"),
    ("NC", "2018-05-08", (35, 34, 31), "derived"),
    ("NC", "2024-03-05", (30, 29, 21, 20), "skipped_nomination_threshold"),
    ("NC", "2024-03-05", (31, 29, 21, 19), "derived"),
    ("GA", "2026-05-19", (40, 35, 25), "skipped_nomination_threshold"),
    ("GA", "2026-05-19", (50, 30, 20), "skipped_nomination_threshold"),
    ("GA", "2026-05-19", (51, 30, 19), "derived"),
    ("TX", "2026-03-03", (40, 35, 25), "skipped_unsupported_nomination_rule"),
])
def test_primary_nomination_thresholds_follow_state_and_date(state, day, votes, outcome):
    election = _election("primary", state)
    election.election_date = day
    election.save(update_fields=["election_date"])
    race = _race(election, party="Republican")
    for i, votes_for_candidate in enumerate(votes):
        _row(race, str(i), votes_for_candidate, party="Republican")
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
@pytest.mark.parametrize("votes,outcome", [((140, 30, 20, 10), "skipped_nomination_threshold"),
                                          ((139, 31, 20, 10), "derived")])
def test_nc_multi_seat_primary_threshold_uses_votes_divided_by_seats(votes, outcome):
    # For two seats and 200 votes, each nominee must exceed 30 votes.
    race = _race(_election("primary", "NC"), party="Republican", seats=2)
    for i, count in enumerate(votes):
        _row(race, str(i), count)
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["NC", "GA"])
def test_supported_two_candidate_runoff_can_derive(state):
    race = _race(_election("primary_runoff", state), party="Republican")
    _row(race, "A", 51)
    _row(race, "B", 49)
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["A"]


@pytest.mark.django_db
def test_unknown_runoff_structure_is_skipped():
    race = _race(_election("primary_runoff", "NC"), party="Republican", seats=2)
    _row(race, "A", 60)
    _row(race, "B", 40)
    _row(race, "C", 30)
    assert derive_winners(race).outcome == "skipped_unsupported_nomination_rule"


@pytest.mark.django_db
def test_consolidated_primary_canonicalizes_party_aliases():
    race = _race(_election("primary", "PA"))
    _row(race, "A", 60, party="Dem")
    _row(race, "B", 40, party="Democratic")
    _row(race, "C", 30, party="Republican")
    assert derive_and_apply(race) == "derived"
    assert _winners(race) == ["A", "C"]


@pytest.mark.django_db
@pytest.mark.parametrize("title,party", [("US President", "Republican"),
                                       ("State Representative District 3", "Nonpartisan")])
def test_primary_preferences_and_nonpartisan_contests_are_not_party_nominations(title, party):
    race = _race(_election("primary", "NC"), party=party, title=title)
    _row(race, "A", 70, party=party)
    _row(race, "B", 30, party=party)
    assert derive_winners(race).outcome == "skipped_unsupported_nomination_rule"


@pytest.mark.django_db
def test_nc_special_with_unresolved_election_classification_is_skipped():
    race = _race(_election("special", "NC"), title="US HOUSE OF REPRESENTATIVES DISTRICT 03 (REP)")
    _row(race, "A", 35)
    _row(race, "B", 34)
    _row(race, "C", 31)
    assert derive_winners(race).outcome == "skipped_election_classification"


@pytest.mark.django_db
def test_primary_write_ins_require_supported_eligibility_and_denominator():
    race = _race(_election("primary", "GA"), party="Republican")
    _row(race, "A", 51)
    _row(race, "B", 49)
    _row(race, None, 20, is_write_in_aggregate=True)
    assert derive_winners(race).outcome == "skipped_unsupported_nomination_rule"


@pytest.mark.django_db
@pytest.mark.parametrize("write_ins,outcome", [(5, "derived"), (60, "skipped_unsupported_nomination_rule"),
                                            (61, "skipped_unsupported_nomination_rule")])
def test_plurality_primary_scattered_write_ins_cannot_reach_winning_seat(write_ins, outcome):
    race = _race(_election("primary", "MA"), party="Democratic")
    _row(race, "A", 60)
    _row(race, "B", 40)
    _row(race, None, write_ins, is_write_in_aggregate=True)
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
@pytest.mark.parametrize("votes,outcome", [(5, "derived"), (70, "skipped_unsupported_nomination_rule")])
def test_named_primary_write_in_winner_requires_eligibility_evidence(votes, outcome):
    race = _race(_election("primary", "MA"), party="Democratic")
    _row(race, "A", 60)
    row = _row(race, "Write-in", votes)
    Candidate.objects.filter(pk=row.candidate_id).update(candidate_status="write_in")
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
def test_new_nomination_guard_clears_a_previous_derived_nominee():
    race = _race(_election("primary", "GA"), party="Republican")
    a = _row(race, "A", 40)
    _row(race, "B", 35)
    _row(race, "C", 25)
    apply_derivation(race, Derivation("derived", [a.pk]))
    assert derive_and_apply(race) == "skipped_nomination_threshold"
    assert _winners(race) == []


@pytest.mark.django_db
@pytest.mark.parametrize("district", ["1st", "5th", "8th"])
def test_verified_ma_council_district_is_one_seat(district):
    race = _race(_election("primary", "MA"), party="Democratic", title="Governor's Council")
    race.source = "ma_sos"
    race.jurisdiction = district
    race.source_metadata = {"electionstats_id": 172925, "contest_code": "172925", "party_code": "Democratic"}
    race.save()
    _row(race, "A", 60)
    _row(race, "B", 40)
    for _ in range(2):
        assert derive_and_apply(race) == "derived"
        assert _winners(race) == ["A"]
    race.refresh_from_db()
    assert race.vote_method == "single_choice"
    assert race.max_selections == 1


@pytest.mark.django_db
@pytest.mark.parametrize("state,source,district,meta", [
    ("MA", "ma_sos", "Statewide", {"electionstats_id": 1, "contest_code": "1"}),
    ("MA", "ma_sos", "9th", {"electionstats_id": 1, "contest_code": "1"}),
    ("MA", "ma_sos", "1st", {}),
    ("MA", "civic_api", "1st", {"electionstats_id": 1, "contest_code": "1"}),
    ("NC", "ma_sos", "1st", {"electionstats_id": 1, "contest_code": "1"}),
])
def test_unverified_council_district_keeps_unknown_seat_guard(state, source, district, meta):
    race = _race(_election(state=state), title="Governor's Council")
    race.source, race.jurisdiction, race.source_metadata = source, district, meta
    race.save()
    _row(race, "A", 60)
    _row(race, "B", 40)
    assert derive_winners(race).outcome == "skipped_unknown_seats"


@pytest.mark.django_db
@pytest.mark.parametrize("candidate_party,normalized,outcome", [
    ("", "DEM", "derived"),
    ("Dem", "DEM", "derived"),
    ("Dem", "REP", "skipped_primary_unpartitioned"),
    ("Republican", "REP", "skipped_primary_unpartitioned"),
])
def test_split_primary_party_metadata_must_agree(candidate_party, normalized, outcome):
    race = _race(_election("primary", "MA"), party="Democratic")
    row = _row(race, "A", 60, party=candidate_party)
    Candidate.objects.filter(pk=row.candidate_id).update(normalized_party=normalized)
    assert derive_winners(race).outcome == outcome


@pytest.mark.django_db
def test_backfill_dry_run_preserves_previous_flags(capsys):
    from django.core.management import call_command

    race = _race(_election("primary", "GA"), party="Republican")
    a = _row(race, "A", 40)
    _row(race, "B", 35)
    _row(race, "C", 25)
    apply_derivation(race, Derivation("derived", [a.pk]))
    call_command("derive_winners", dry_run=True)
    assert "skipped_nomination_threshold" in capsys.readouterr().out
    assert _winners(race) == ["A"]
    call_command("derive_winners")
    assert _winners(race) == []


@pytest.mark.django_db
def test_backfill_reloads_source_outcomes_after_prefetch(monkeypatch):
    from django.core.management import call_command
    from django.db.models.query import QuerySet

    race = _race(_election())
    a = _row(race, "A", 60)
    b = _row(race, "B", 40)
    derive_and_apply(race)
    original_iterator = QuerySet.iterator

    def imported_after_prefetch(queryset, *args, **kwargs):
        for item in original_iterator(queryset, *args, **kwargs):
            if queryset.model is Race and item.pk == race.pk:
                # Source correction lands after the command has prefetched derived rows.
                Race.objects.filter(pk=race.pk).update(source_metadata={})
                OfficialResult.objects.filter(pk=a.pk).update(is_winner=False)
                OfficialResult.objects.filter(pk=b.pk).update(is_winner=True)
            yield item

    monkeypatch.setattr(QuerySet, "iterator", imported_after_prefetch)
    call_command("derive_winners")
    assert _winners(race) == ["B"]
    race.refresh_from_db()
    assert DERIVED_MARKER not in race.source_metadata


@pytest.mark.django_db(transaction=True)
def test_derivation_waits_for_import_transaction():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from django.db import close_old_connections, connection, transaction

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    race = _race(_election())
    a = _row(race, "A", 60)
    b = _row(race, "B", 40)
    derive_and_apply(race)
    started = Event()
    worker_pid = []

    def derive_on_other_connection():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
            started.set()
            return derive_and_apply(Race.objects.get(pk=race.pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Race.objects.select_for_update().get(pk=race.pk)
            future = pool.submit(derive_on_other_connection)
            assert started.wait(timeout=5)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline and not future.done():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [worker_pid[0]])
                    blocked = cursor.fetchone()[0]
                if blocked:
                    break
                sleep(0.01)
            assert blocked, "Derivation must wait for the importing transaction's row lock"
            # Import publishes source flags and relinquishes derived ownership atomically.
            Race.objects.filter(pk=race.pk).update(source_metadata={})
            OfficialResult.objects.filter(pk=a.pk).update(is_winner=False)
            OfficialResult.objects.filter(pk=b.pk).update(is_winner=True)
        assert future.result(timeout=5) == "skipped_source_set"
    assert _winners(race) == ["B"]


@pytest.mark.django_db
def test_runoff_with_zero_vote_party_stays_unknown():
    race = _race(_election("primary_runoff", "NC"))
    _row(race, "A", 60, party="Democratic")
    _row(race, "B", 40, party="Democratic")
    _row(race, "C", 0, party="Republican")
    assert derive_winners(race).outcome == "skipped_zero_votes"


@pytest.mark.django_db
@pytest.mark.parametrize("state,etype,day,seats,votes", [
    ("NC", "primary", "2013-05-07", 1, (70, 30)),
    ("GA", "primary", "2024-05-21", 1, (70, 30)),
    ("GA", "primary", "2026-05-19", 2, (70, 30)),
    ("NC", "primary_runoff", "2026-06-02", 1, (60, 30, 10)),
])
def test_nomination_rule_boundaries_remain_unsupported(state, etype, day, seats, votes):
    election = _election(etype, state)
    election.election_date = day
    election.save(update_fields=["election_date"])
    race = _race(election, party="Republican", seats=seats)
    for index, count in enumerate(votes):
        _row(race, str(index), count)
    assert derive_winners(race).outcome == "skipped_unsupported_nomination_rule"


@pytest.mark.django_db
def test_ranked_choice_method_without_round_rows_stays_unknown():
    race = _race(_election())
    race.vote_method = Race.VoteMethod.RANKED_CHOICE
    _row(race, "A", 60)
    _row(race, "B", 40)
    assert derive_winners(race).outcome == "skipped_ranked_choice"
