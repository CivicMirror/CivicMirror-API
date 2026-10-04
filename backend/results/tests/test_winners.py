"""Winner derivation rules (results/winners.py)."""
import pytest

from elections.models import Candidate, Election, Race
from results.models import OfficialResult
from results.winners import DERIVED_MARKER, apply_derivation, derive_and_apply, derive_winners

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


@pytest.mark.django_db
def test_ingest_hook_respects_setting(settings):
    from results.tasks import _process_race_results  # noqa: F401  (hook lives in ingest_official_results)
    settings.DERIVE_WINNERS_ENABLED = False
    race = _race(_election())
    _row(race, "A", 10)
    # With the setting off, nothing derives winners implicitly.
    assert _winners(race) == []
    apply_derivation(race, derive_winners(race))
    assert _winners(race) == ["A"]


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
