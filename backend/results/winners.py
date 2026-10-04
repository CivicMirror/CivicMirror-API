"""
Derive is_winner for certified official results when the source didn't provide it.

Most adapters never set OfficialResult.is_winner, so certified races showed no winner. This marks
winners on a race's contest-total rows (jurisdiction_fragment == "") using conservative rules. When
a rule can't be applied safely, the race is skipped and left null rather than guessed.

Skips (outcome strings, used by the backfill report):
  skipped_measure                ballot measures (passage thresholds vary)
  skipped_not_certified          race isn't results_certified
  skipped_source_set             the adapter already set is_winner (True or False) on any row
  skipped_ranked_choice          rows carry round_number
  skipped_no_totals              no "" contest-total candidate rows. Sub-jurisdiction rows aren't
                                 summed, because fragments may overlap (precincts inside counties).
  skipped_unofficial             a contest-total row isn't result_type=official
  skipped_zero_votes             every total is 0 / null
  skipped_top_two_primary        primary in a top-two/top-four state (party != nomination)
  skipped_primary_unpartitioned  consolidated primary (race.party blank) with a candidate whose
                                 party is unknown, so the per-party nomination can't be computed
  skipped_tie                    tie at the last winning seat
Success: derived. Races whose winners were derived carry source_metadata["winners_derived"] = True
and are re-derived when corrected results arrive. Adapter-set races never get the marker.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DERIVED_MARKER = "winners_derived"
TOP_TWO_PRIMARY_STATES = frozenset({"CA", "WA", "AK", "LA"})
PRIMARY_TYPES = frozenset({"primary", "primary_runoff"})


@dataclass
class Derivation:
    outcome: str
    winner_row_ids: list[int] = field(default_factory=list)
    loser_row_ids: list[int] = field(default_factory=list)


def _seats(race) -> int:
    return max(1, race.max_selections or 1) if race.vote_method == race.VoteMethod.MULTI_SEAT else 1


def derive_winners(race, rows=None) -> Derivation:
    """Compute (without writing) the winner/loser contest-total rows for a race."""
    from elections.models import Race
    from results.models import OfficialResult

    if race.race_type != Race.RaceType.CANDIDATE:
        return Derivation("skipped_measure")
    if race.certification_status != Race.CertificationStatus.RESULTS_CERTIFIED:
        return Derivation("skipped_not_certified")

    if rows is None:
        rows = list(race.official_results.select_related("candidate"))
    derived_before = bool((race.source_metadata or {}).get(DERIVED_MARKER))
    if not derived_before and any(r.is_winner is not None for r in rows):
        return Derivation("skipped_source_set")
    if any(r.round_number is not None for r in rows):
        return Derivation("skipped_ranked_choice")

    totals = [r for r in rows if r.jurisdiction_fragment == "" and r.candidate_id and not r.is_write_in_aggregate]
    if not totals:
        return Derivation("skipped_no_totals")
    if any(r.result_type != OfficialResult.ResultType.OFFICIAL for r in totals):
        return Derivation("skipped_unofficial")
    if not any((r.vote_count or 0) > 0 for r in totals):
        return Derivation("skipped_zero_votes")

    election = race.election
    groups: dict[str, list] = {}
    if election.election_type in PRIMARY_TYPES and not race.party:
        if election.state in TOP_TWO_PRIMARY_STATES:
            return Derivation("skipped_top_two_primary")
        # Consolidated primary: one nomination per party.
        for row in totals:
            party = (row.candidate.party or "").strip()
            if not party:
                return Derivation("skipped_primary_unpartitioned")
            groups.setdefault(party.lower(), []).append(row)
    elif election.election_type in PRIMARY_TYPES and election.state in TOP_TWO_PRIMARY_STATES:
        return Derivation("skipped_top_two_primary")
    else:
        groups[""] = totals

    seats = _seats(race)
    winners, losers = [], []
    for group in groups.values():
        ranked = sorted(group, key=lambda r: r.vote_count or 0, reverse=True)
        if len(ranked) > seats and (ranked[seats - 1].vote_count or 0) == (ranked[seats].vote_count or 0):
            return Derivation("skipped_tie")
        winners += [r.pk for r in ranked[:seats]]
        losers += [r.pk for r in ranked[seats:]]
    return Derivation("derived", winners, losers)


def apply_derivation(race, derivation: Derivation) -> None:
    """Write a 'derived' result: winners True, losers False on contest-total rows; mark the race."""
    from results.models import OfficialResult

    totals = OfficialResult.objects.filter(race=race, jurisdiction_fragment="")
    meta = dict(race.source_metadata or {})
    if derivation.outcome != "derived":
        if meta.get(DERIVED_MARKER):
            # Previously derived, but corrected results no longer support a winner (e.g. a recount
            # tie): clear our own flags rather than leave stale winners.
            totals.update(is_winner=None)
            meta.pop(DERIVED_MARKER)
            race.source_metadata = meta
            race.save(update_fields=["source_metadata"])
        return
    totals.filter(pk__in=derivation.winner_row_ids).update(is_winner=True)
    totals.filter(pk__in=derivation.loser_row_ids).update(is_winner=False)
    if not meta.get(DERIVED_MARKER):
        meta[DERIVED_MARKER] = True
        race.source_metadata = meta
        race.save(update_fields=["source_metadata"])


def derive_and_apply(race) -> str:
    """Derive and write winners for one race; returns the outcome."""
    derivation = derive_winners(race)
    apply_derivation(race, derivation)
    return derivation.outcome
