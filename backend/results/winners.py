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
  skipped_ambiguous_contest      race bootstrapped from a results feed whose title doesn't identify a
                                 unique contest. County/local offices like "SHERIFF (DEM)" merge
                                 several counties' contests into one race (NC), so only federal,
                                 statewide and numbered-district scopes are derived for those races.
  skipped_unknown_seats          the number of seats isn't known. Most sources never record it
                                 (bootstrapped races default to single-seat; MA/TN hard-code 1),
                                 so only offices that are inherently one seat per contest (Governor,
                                 U.S./state legislative districts, Sheriff, a named judicial seat, ...)
                                 are derived, unless the race explicitly records multi_seat.
  skipped_election_classification NC election type needs reconciliation before applying a rule
  skipped_unsupported_nomination_rule no verified rule covers the primary's date, structure or candidates
  skipped_nomination_threshold   leader(s) do not meet the state's threshold for nomination
Success: derived. Races whose winners were derived carry source_metadata["winners_derived"] = True
and are re-derived when corrected results arrive. Adapter-set races never get the marker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from aggregation.identity import normalize_party

DERIVED_MARKER = "winners_derived"
TOP_TWO_PRIMARY_STATES = frozenset({"CA", "WA", "AK", "LA"})
PRIMARY_TYPES = frozenset({"primary", "primary_runoff"})
PLURALITY_PRIMARY_STATES = frozenset({"MA", "TN", "PA", "CT", "MO"})
NOMINATION_PARTIES = frozenset({"DEM", "REP", "LIB", "GRN", "CON", "WFP"})
# Scopes whose title identifies one contest even for races bootstrapped from results feeds.
UNIQUE_CONTEST_SCOPES = frozenset({"federal", "statewide", "district"})

# Offices that elect exactly one person per contest.
_SINGLE_SEAT_RE = re.compile(
    r"\bPRESIDENT\b|\bLIEUTENANT GOVERNOR\b|\bGOVERNOR\b(?!'?S COUNCIL)|\bATTORNEY GENERAL\b|"
    r"\bSECRETARY OF (STATE|THE COMMONWEALTH)\b|\bTREASURER\b|\bAUDITOR\b|\bCOMPTROLLER\b|\bCONTROLLER\b|"
    r"\bCOMMISSIONER OF [A-Z]|\bSUPERINTENDENT OF PUBLIC INSTRUCTION\b|"
    r"\b(U\.?\s?S\.?|UNITED STATES)\s+(SENATE|SENATOR|HOUSE|REPRESENTATIVE)|\bCONGRESS|"
    r"\bSTATE\s+(SENATE|SENATOR|HOUSE|REPRESENTATIVE|ASSEMBLY)\b|\bHOUSE OF (REPRESENTATIVES|DELEGATES)\b|"
    r"\bSENATE\b.*\bDISTRICT\b|\bSHERIFF\b|\bDISTRICT ATTORNEY\b|\bPROSECUTING ATTORNEY\b|"
    r"\bCLERK OF\b|\bREGISTER OF (DEEDS|PROBATE)\b|\bMAYOR\b|\bCORONER\b|\bSURROGATE\b|"
    r"\b(JUDGE|JUSTICE)\b.*\bSEAT\b|\bSEAT\b.*\b(JUDGE|JUSTICE)\b|\bCHIEF JUSTICE\b|"
    r"^STATE (REPRESENTATIVE|SENATOR)$",
    re.I,
)
# Even when a single-seat word appears, these indicate a multi-member body or an unnumbered seat.
_MULTI_MEMBER_RE = re.compile(
    r"\bAT[- ]LARGE\b|\bBOARD\b|\bCOUNCIL\b|\bCOMMISSION\b|\bCOMMISSIONERS\b|\bMEMBERS?\b|\bSUPERVISORS?\b|"
    r"\bTRUSTEES?\b|\bCOMMITTEE\b|\bCONSTABLES?\b|\bJUSTICES? OF THE PEACE\b",
    re.I,
)


def is_single_seat_office(office_title: str) -> bool:
    title = office_title or ""
    return bool(_SINGLE_SEAT_RE.search(title)) and not _MULTI_MEMBER_RE.search(title)


@dataclass
class Derivation:
    outcome: str
    winner_row_ids: list[int] = field(default_factory=list)
    loser_row_ids: list[int] = field(default_factory=list)


def _seats(race) -> int:
    return max(1, race.max_selections or 1) if race.vote_method == race.VoteMethod.MULTI_SEAT else 1


def _ma_council_district(race) -> bool:
    """MA Constitution Amendment XVI: one councillor in each of eight districts."""
    meta = race.source_metadata or {}
    return (
        race.election.state == "MA"
        and race.source == "ma_sos"
        and race.office_title.replace("’", "'").casefold() == "governor's council"
        and race.geography_scope == "district"
        and race.jurisdiction in {"1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th"}
        and str(meta.get("electionstats_id", "")).isdigit()
        and str(meta.get("contest_code", "")) == str(meta.get("electionstats_id"))
    )


def _party(obj) -> str:
    # A stale normalized field must not silently override a conflicting source label.
    raw = normalize_party(obj.party or "")
    normalized = normalize_party(obj.normalized_party or "")
    return "" if raw and normalized and raw != normalized else raw or normalized


def _nomination_check(race, rows, groups, seats) -> str | None:
    """Return a skip reason unless a verified nomination rule covers this contest.

    See docs/results-winner-rules.md for source laws and intentionally unsupported cases.
    Below-threshold NC plurality is not evidence that a second primary was waived.
    """
    election = race.election
    state = election.state
    day = date.fromisoformat(str(election.election_date))
    unsupported = "skipped_unsupported_nomination_rule"
    if (day < date(2014 if state == "NC" else 2026, 1, 1)
            or state not in PLURALITY_PRIMARY_STATES | {"NC", "GA"}):
        return unsupported
    if re.search(r"\bPRESIDENT(?:IAL)?\b|\bDELEGATE\b", race.office_title, re.I):
        return unsupported
    if any(party not in NOMINATION_PARTIES for party in groups):
        return unsupported
    scattered = [r for r in rows if r.jurisdiction_fragment == "" and r.is_write_in_aggregate]
    if any(r.vote_count is None or r.result_type != "official" for r in scattered):
        return unsupported
    scattered_votes = sum(r.vote_count for r in scattered)
    if state not in PLURALITY_PRIMARY_STATES and scattered_votes:
        return unsupported
    for group in groups.values():
        if not any((r.vote_count or 0) > 0 for r in group):
            return "skipped_zero_votes"
        ranked = sorted(group, key=lambda r: r.vote_count or 0, reverse=True)
        winners = ranked[:seats]
        if any(r.candidate.candidate_status != "running" for r in winners):
            return unsupported
        # Even assigning every unidentified write-in to one person cannot change a
        # plurality result when the total is below the last winning candidate.
        if scattered_votes and (len(winners) < seats or scattered_votes >= (winners[-1].vote_count or 0)):
            return unsupported
    if election.election_type == "primary_runoff":
        if state not in {"NC", "GA"} or seats != 1 or any(len(g) > 2 for g in groups.values()):
            return unsupported
        return None
    if state == "GA" and seats != 1:
        return unsupported
    threshold = (40 if day < date(2018, 1, 1) else 30) if state == "NC" else 50 if state == "GA" else 0
    for group in groups.values():
        total = sum(r.vote_count or 0 for r in group)
        if threshold and any(
            (r.vote_count or 0) * 100 * seats <= total * threshold
            for r in sorted(group, key=lambda r: r.vote_count or 0, reverse=True)[:seats]
        ):
            return "skipped_nomination_threshold"
    return None


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
    if race.vote_method == Race.VoteMethod.RANKED_CHOICE or any(r.round_number is not None for r in rows):
        return Derivation("skipped_ranked_choice")

    totals = [r for r in rows if r.jurisdiction_fragment == "" and r.candidate_id and not r.is_write_in_aggregate]
    if not totals:
        return Derivation("skipped_no_totals")
    if any(r.result_type != OfficialResult.ResultType.OFFICIAL for r in totals):
        return Derivation("skipped_unofficial")
    if not any((r.vote_count or 0) > 0 for r in totals):
        return Derivation("skipped_zero_votes")

    election = race.election
    if election.state == "NC" and election.election_type not in {"general", *PRIMARY_TYPES}:
        return Derivation("skipped_election_classification")
    groups: dict[str, list] = {}
    if election.election_type in PRIMARY_TYPES:
        if election.state in TOP_TWO_PRIMARY_STATES:
            return Derivation("skipped_top_two_primary")
        race_party = _party(race)
        if race.party or race.normalized_party:
            if not race_party or any(
                (r.candidate.party or r.candidate.normalized_party) and _party(r.candidate) != race_party
                for r in totals
            ):
                return Derivation("skipped_primary_unpartitioned")
            groups[race_party] = totals
        else:
            # Consolidated primary: one nomination per canonical party, not per label alias.
            for row in totals:
                party = _party(row.candidate)
                if not party:
                    return Derivation("skipped_primary_unpartitioned")
                groups.setdefault(party, []).append(row)
    else:
        groups[""] = totals

    if race.source == Race.Source.RESULTS_ADAPTER and race.geography_scope not in UNIQUE_CONTEST_SCOPES:
        return Derivation("skipped_ambiguous_contest")
    if (race.vote_method != race.VoteMethod.MULTI_SEAT
            and not is_single_seat_office(race.office_title) and not _ma_council_district(race)):
        return Derivation("skipped_unknown_seats")
    seats = _seats(race)
    if election.election_type in PRIMARY_TYPES:
        reason = _nomination_check(race, rows, groups, seats)
        if reason:
            return Derivation(reason)
    winners, losers = [], []
    for group in groups.values():
        ranked = sorted(group, key=lambda r: r.vote_count or 0, reverse=True)
        if len(ranked) > seats and (ranked[seats - 1].vote_count or 0) == (ranked[seats].vote_count or 0):
            return Derivation("skipped_tie")
        winners += [r.pk for r in ranked[:seats]]
        losers += [r.pk for r in ranked[seats:]]
    return Derivation("derived", winners, losers)


def clear_derived_winners(race) -> None:
    """Retire this race's previous derivation before a skip or incoming source outcome."""
    from results.models import OfficialResult

    meta = dict(race.source_metadata or {})
    if meta.pop(DERIVED_MARKER, None):
        OfficialResult.objects.filter(race=race, jurisdiction_fragment="").update(is_winner=None)
        race.source_metadata = meta
        race.save(update_fields=["source_metadata"])


def apply_derivation(race, derivation: Derivation) -> None:
    """Write a 'derived' result: winners True, losers False on contest-total rows; mark the race."""
    from results.models import OfficialResult

    totals = OfficialResult.objects.filter(race=race, jurisdiction_fragment="")
    meta = dict(race.source_metadata or {})
    if derivation.outcome != "derived":
        clear_derived_winners(race)
        return
    totals.filter(pk__in=derivation.winner_row_ids).update(is_winner=True)
    totals.filter(pk__in=derivation.loser_row_ids).update(is_winner=False)
    if not meta.get(DERIVED_MARKER):
        meta[DERIVED_MARKER] = True
        race.source_metadata = meta
        race.save(update_fields=["source_metadata"])


@transaction.atomic
def derive_and_apply(race) -> str:
    """Derive and write winners for one race; returns the outcome."""
    from elections.models import Race

    locked_race = Race.objects.select_for_update(of=("self",)).select_related("election").get(pk=race.pk)
    derivation = derive_winners(locked_race)
    apply_derivation(locked_race, derivation)
    race.source_metadata = locked_race.source_metadata
    return derivation.outcome
