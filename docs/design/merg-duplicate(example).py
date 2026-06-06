"""
Recompute ``Race.canonical_key`` under the *current* normalization rules and
merge duplicate Race rows that now collapse to the same key.

WHY THIS EXISTS
---------------
``Race.canonical_key`` is ``unique=True`` and stored in the DB. When the
normalization in ``aggregation.identity`` is strengthened (geo-suffix stripping,
bare-state-code OCD collapse), previously-distinct keys begin colliding. If the
next sync runs *before* stored keys are recomputed, ingest computes the new key,
fails to match the old stored key, and creates a *fresh* duplicate instead of
merging. This command must run immediately after deploy, before the next sync.

DEPLOYMENT ORDER (critical)
---------------------------
1. Pause the sync schedulers (sync-ca-sos, etc.).
2. Deploy the identity.py / mappers.py changes.
3. Run this command (``--dry-run`` first to preview).
4. Resume schedulers.

IDEMPOTENCY
-----------
A second run over already-merged data is a no-op: keys already equal their
recompute, and there are no remaining collision groups.

NOTE ON IMPORTS
---------------
``OfficialResult`` is imported below with a fallback. If it lives in a dedicated
results app rather than ``elections.models``, adjust the import.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone as _utc
from math import inf

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from aggregation.identity import (
    name_match_key,
    normalize_party,
    race_canonical_key,
)
from aggregation.precedence import field_group_for, resolve_rank

from elections.models import Candidate, MeasureOption, Race  # noqa: F401

try:
    from elections.models import OfficialResult
except ImportError:  # pragma: no cover - adjust if results live elsewhere
    from results.models import OfficialResult

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Key helpers
# --------------------------------------------------------------------------- #
def _election_key(election):
    # Mirror ingest_race exactly: fall back to e<pk> when canonical_key is null.
    return election.canonical_key or f"e{election.pk}"


def _new_key(race):
    return race_canonical_key(
        _election_key(race.election),
        race.office_title,
        race.ocd_division_id or "",
        race.race_type,
    )


def _identity_state(race):
    # Mirror ingest_race: election.state or "*".
    return (race.election.state or "*")


def _identity_rank(source, state):
    return resolve_rank(state, "identity", source)


# --------------------------------------------------------------------------- #
# Provenance-aware field / source merge
# --------------------------------------------------------------------------- #
def _merge_fields(target, donor, state):
    """Copy donor field values into ``target`` where the donor's owning source
    *strictly* out-ranks the target's (lower resolve_rank == higher precedence).

    Ties keep the target's existing value (the merge winner). This is faithful to
    each field's recorded provenance, unlike re-applying every field under a
    single source. Returns the list of copied field names.
    """
    tp = dict(target.field_provenance or {})
    dp = donor.field_provenance or {}
    copied = []
    for fname, donor_src in dp.items():
        group = field_group_for(fname)
        donor_rank = resolve_rank(state, group, donor_src)
        target_src = tp.get(fname)
        target_rank = resolve_rank(state, group, target_src) if target_src else inf
        if donor_rank < target_rank:
            setattr(target, fname, getattr(donor, fname))
            tp[fname] = donor_src
            copied.append(fname)
    target.field_provenance = tp
    return copied


def _merge_sources(target, donor):
    merged = list(target.contributing_sources or [])
    for s in donor.contributing_sources or []:
        if s not in merged:
            merged.append(s)
    target.contributing_sources = merged


def _find_matching_candidate(winner_race, loser_cand):
    """Same matching rule as ingest_candidate: normalized name + normalized
    party; nonpartisan (empty party) matches on name only."""
    norm_name = name_match_key(loser_cand.name)
    norm_party = normalize_party(loser_cand.party)
    for cand in winner_race.candidates.all():
        if name_match_key(cand.name) == norm_name and (
            norm_party == "" or normalize_party(cand.party) == norm_party
        ):
            return cand
    return None


# --------------------------------------------------------------------------- #
# Per-loser merge
# --------------------------------------------------------------------------- #
def _merge_loser_into_winner(winner, loser, state, stats):
    """Fold one loser race into the winner. Does NOT delete the loser race or
    touch the winner's canonical_key — the caller does that after all losers in
    the group are processed (so freed keys don't collide with the winner)."""

    record = {
        "loser_race_id": loser.pk,
        "loser_canonical_key": loser.canonical_key,
        "candidate_remap": {},   # loser_cand_id -> winner_cand_id
        "option_remap": {},      # loser_opt_id  -> winner_opt_id
        "results_moved": 0,
        "potential_duplicate_results": 0,
    }

    # --- Candidates: move (FK reassign) when no equivalent, else merge ------- #
    cand_remap = {}
    for loser_cand in list(loser.candidates.all()):
        match = _find_matching_candidate(winner, loser_cand)

        if match is None:
            # No equivalent on winner. Guard the exact-name unique constraint:
            # two distinct normalized names can in principle still share an exact
            # string (normalization is lossy). If that happens, treat the
            # same-name row as the match rather than crashing on the move.
            same_name = winner.candidates.filter(name=loser_cand.name).first()
            if same_name is not None:
                match = same_name
            else:
                loser_cand.race = winner
                loser_cand.save(update_fields=["race"])
                cand_remap[loser_cand.id] = loser_cand.id
                stats["candidates_moved"] += 1
                continue

        # Equivalent exists -> merge fields/sources into the winner candidate.
        if match.official_results.exists():
            stats["potential_duplicate_results"] += 1
            record["potential_duplicate_results"] += 1
            logger.warning(
                "merge_duplicate_races: winner candidate %s already has results; "
                "loser candidate %s results will be appended (possible duplicate rows)",
                match.pk, loser_cand.pk,
            )
        _merge_fields(match, loser_cand, state)
        _merge_sources(match, loser_cand)
        match.normalized_party = normalize_party(match.party)
        match.save()
        cand_remap[loser_cand.id] = match.id
        stats["candidates_merged"] += 1

    record["candidate_remap"] = {str(k): v for k, v in cand_remap.items()}

    # --- Measure options: move when no equivalent, else merge by label ------- #
    opt_remap = {}
    for loser_opt in list(loser.measure_options.all()):
        match_opt = winner.measure_options.filter(
            option_label=loser_opt.option_label
        ).first()
        if match_opt is None:
            loser_opt.race = winner
            loser_opt.save(update_fields=["race"])
            opt_remap[loser_opt.id] = loser_opt.id
            stats["options_moved"] += 1
        else:
            opt_remap[loser_opt.id] = match_opt.id
            stats["options_merged"] += 1

    record["option_remap"] = {str(k): v for k, v in opt_remap.items()}

    # --- Results: reassign race, remap candidate / measure_option ----------- #
    for res in list(OfficialResult.objects.filter(race=loser)):
        update = ["race"]
        res.race = winner
        if res.candidate_id is not None and res.candidate_id in cand_remap:
            new_cid = cand_remap[res.candidate_id]
            if new_cid != res.candidate_id:
                res.candidate_id = new_cid
                update.append("candidate")
        if res.measure_option_id is not None and res.measure_option_id in opt_remap:
            new_oid = opt_remap[res.measure_option_id]
            if new_oid != res.measure_option_id:
                res.measure_option_id = new_oid
                update.append("measure_option")
        res.save(update_fields=update)
        record["results_moved"] += 1
        stats["results_moved"] += 1

    # --- Race-level fields + sources ---------------------------------------- #
    _merge_fields(winner, loser, state)
    _merge_sources(winner, loser)

    return record


# --------------------------------------------------------------------------- #
# Group processors
# --------------------------------------------------------------------------- #
def _process_collision_group(new_key, race_pks, stats, audit, apply_changes):
    """Merge a set of races that collapse to ``new_key`` into a single winner."""
    with transaction.atomic():
        # Lock the group for the duration of the merge.
        races = list(
            Race.objects.select_for_update()
            .select_related("election")
            .filter(pk__in=race_pks)
        )
        if len(races) < 2:
            return  # changed under us; nothing to merge

        state = _identity_state(races[0])
        # Winner = highest-precedence identity source (lowest rank), pk tiebreak.
        winner = min(races, key=lambda r: (_identity_rank(r.source, state), r.pk))
        losers = [r for r in races if r.pk != winner.pk]

        group_record = {
            "new_key": new_key,
            "winner_race_id": winner.pk,
            "winner_source": winner.source,
            "losers": [],
        }

        if not apply_changes:
            for loser in losers:
                group_record["losers"].append({
                    "loser_race_id": loser.pk,
                    "loser_source": loser.source,
                    "candidates": loser.candidates.count(),
                    "measure_options": loser.measure_options.count(),
                    "results": OfficialResult.objects.filter(race=loser).count(),
                })
            audit(group_record)
            stats["groups_merged"] += 1
            stats["races_deleted"] += len(losers)
            return

        try:
            for loser in losers:
                group_record["losers"].append(
                    _merge_loser_into_winner(winner, loser, state, stats)
                )

            # Delete losers FIRST so their (now-stale) unique keys are freed
            # before the winner claims new_key.
            Race.objects.filter(pk__in=[l.pk for l in losers]).delete()

            if winner.contributing_sources:
                winner.source = min(
                    winner.contributing_sources,
                    key=lambda s: _identity_rank(s, state),
                )
            winner.canonical_key = new_key
            winner.save()

        except IntegrityError as exc:
            # Most likely: new_key already held by an out-of-scope race.
            # Roll back the whole group and flag the winner for manual review.
            logger.error(
                "merge_duplicate_races: IntegrityError merging group %s (winner %s): %s",
                new_key, winner.pk, exc,
            )
            transaction.set_rollback(True)
            group_record["error"] = str(exc)
            stats["conflicts"] += 1
            audit(group_record)
            # Flag outside the rolled-back transaction.
            Race.objects.filter(pk=winner.pk).update(
                match_confidence=Race.MatchConfidence.FLAGGED
            )
            return

        audit(group_record)
        stats["groups_merged"] += 1
        stats["races_deleted"] += len(losers)


def _process_solo(race_pk, new_key, stats, audit, apply_changes):
    """A lone race whose recomputed key differs from its stored key — just
    update the key (no merge)."""
    if not apply_changes:
        stats["solo_updated"] += 1
        audit({"solo_race_id": race_pk, "new_key": new_key, "dry_run": True})
        return

    with transaction.atomic():
        race = Race.objects.select_for_update().filter(pk=race_pk).first()
        if race is None or race.canonical_key == new_key:
            return
        conflict = (
            Race.objects.filter(canonical_key=new_key).exclude(pk=race.pk).first()
        )
        if conflict is not None:
            logger.warning(
                "merge_duplicate_races: solo race %s -> key %s collides with "
                "out-of-scope race %s; flagging instead of updating",
                race.pk, new_key, conflict.pk,
            )
            race.match_confidence = Race.MatchConfidence.FLAGGED
            race.save(update_fields=["match_confidence"])
            stats["conflicts"] += 1
            audit({
                "solo_race_id": race.pk,
                "new_key": new_key,
                "conflict_race_id": conflict.pk,
            })
            return

        old_key = race.canonical_key
        race.canonical_key = new_key
        race.save(update_fields=["canonical_key"])
        stats["solo_updated"] += 1
        audit({"solo_race_id": race.pk, "old_key": old_key, "new_key": new_key})


# --------------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------------- #
class Command(BaseCommand):
    help = (
        "Recompute Race.canonical_key under current normalization and merge "
        "duplicate races that collapse to the same key. Run immediately after "
        "deploying stronger normalization, before the next sync."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview actions without writing any changes.",
        )
        parser.add_argument(
            "--election-id", type=int, default=None,
            help="Limit to races in a single election.",
        )
        parser.add_argument(
            "--state", type=str, default=None,
            help="Limit to races whose election.state matches (e.g. CA).",
        )
        parser.add_argument(
            "--audit-file", type=str, default=None,
            help="Path for the JSONL audit log (default: timestamped in cwd).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apply_changes = not dry_run

        races = Race.objects.select_related("election").all()
        if options["election_id"] is not None:
            races = races.filter(election_id=options["election_id"])
        if options["state"]:
            races = races.filter(election__state=options["state"].upper())

        # Group every in-scope race by its recomputed key.
        groups = defaultdict(list)  # new_key -> [(pk, current_key)]
        for race in races.iterator():
            try:
                nk = _new_key(race)
            except Exception as exc:  # noqa: BLE001 - never let one bad row abort the run
                logger.error(
                    "merge_duplicate_races: failed to recompute key for race %s: %s",
                    race.pk, exc,
                )
                continue
            groups[nk].append((race.pk, race.canonical_key))

        stats = defaultdict(int)
        audit_path = options["audit_file"] or (
            f"merge_duplicate_races_{datetime.now(_utc):%Y%m%dT%H%M%SZ}.jsonl"
        )

        audit_fh = None
        if not dry_run:
            audit_fh = open(audit_path, "w", encoding="utf-8")

        def audit(record):
            line = json.dumps(record, default=str)
            if audit_fh is not None:
                audit_fh.write(line + "\n")
            logger.info("merge_duplicate_races.audit %s", line)

        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(f"[{mode}] scanning {races.count()} race(s)...")

        try:
            for new_key, members in groups.items():
                if len(members) > 1:
                    self.stdout.write(
                        f"  collision: {len(members)} races -> {new_key}"
                    )
                    _process_collision_group(
                        new_key, [pk for pk, _ in members], stats, audit, apply_changes
                    )
                else:
                    (pk, current_key), = members
                    if current_key != new_key:
                        _process_solo(pk, new_key, stats, audit, apply_changes)
        finally:
            if audit_fh is not None:
                audit_fh.close()

        self.stdout.write(self.style.SUCCESS(f"[{mode}] done."))
        self.stdout.write(
            "  collision groups merged : {groups_merged}\n"
            "  loser races deleted      : {races_deleted}\n"
            "  solo keys updated        : {solo_updated}\n"
            "  candidates moved         : {candidates_moved}\n"
            "  candidates merged        : {candidates_merged}\n"
            "  measure options moved    : {options_moved}\n"
            "  measure options merged   : {options_merged}\n"
            "  official results moved   : {results_moved}\n"
            "  potential dup results    : {potential_duplicate_results}\n"
            "  conflicts (flagged)      : {conflicts}".format(
                **{k: stats[k] for k in (
                    "groups_merged", "races_deleted", "solo_updated",
                    "candidates_moved", "candidates_merged",
                    "options_moved", "options_merged", "results_moved",
                    "potential_duplicate_results", "conflicts",
                )}
            )
        )
        if not dry_run:
            self.stdout.write(f"  audit log: {audit_path}")
        if stats["potential_duplicate_results"]:
            self.stdout.write(self.style.WARNING(
                "  Review potential duplicate results: a winner candidate already "
                "had results when a loser's were appended. Vote counts were NOT "
                "auto-summed."
            ))
