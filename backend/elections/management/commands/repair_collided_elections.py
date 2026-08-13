"""
Rekey stored special Elections onto ``contest_group``-suffixed canonical keys,
splitting the ones that turn out to hold genuinely unrelated contests.
See issue #187.

WHAT THIS COMMAND GUARANTEES
----------------------------
Post-condition, per state: every stored special ``Election``'s
``canonical_key`` equals what that state's live adapter will compute on the
next sync, and every child ``Race.canonical_key`` embeds that new election
key. Rows that cannot be brought to that state are reported and the command
exits non-zero — it never leaves a silent non-convergence behind.

That is a *superset* of "split the collided rows", and deliberately so. Once
an adapter starts computing ``contest_group``, EVERY special election it
emits gets a ``|group``-suffixed key — not just the collided ones. A stored
row still on the bare key would no longer match, and the next sync would mint
a duplicate. So each in-scope Election takes one of two paths:

  * **one distinct grouping value across its races → rekey in place.**
    ``canonical_key`` gains the ``|group`` suffix; races keep their parent.
    This is the path GA and VA take: production investigation found every one
    of their "collided" rows (27 GA, 4 VA) is a single legitimate ballot
    bundling many districts under one ``public_id``/``enr_slug``, so they must
    be rekeyed but must NOT be split. The single-group branch enforces that
    structurally — there is no state exclusion list to keep in sync.
  * **more than one distinct grouping value → split.** Races are reparented
    onto one new per-group Election each, provenance is carried across, and
    the original row is removed.

RACE KEYS ARE PREFIX-SWAPPED, NOT RECOMPUTED
--------------------------------------------
A race key is literally ``<election_key>|<office>|<ocd>|<race_type>[|<variant>]``,
so this command rewrites only the leading election-key segment and carries the
rest over byte-for-byte:

    race.canonical_key = new_election_key + stored[len(old_election_key):]

It does NOT recompute the key from Race model fields the way
``merge_duplicate_races`` does. ``Race`` has no column persisting
``contest_variant``, so a recompute silently drops it — and MA's specials
(``ma_sos/tasks.py``), NC and MD all rely on that suffix to keep party-split
races distinct. Prefix-swapping preserves whatever the adapter last computed,
which is exactly what the adapter will compute again next sync.

Races whose stored key does not start with the old election key (e.g. rows
keyed before the aggregation refactor, or an election with a NULL
canonical_key whose races used the ``e<pk>`` fallback) are left untouched and
reported — they need a look, not a guess.

GROUPING MODES (one per invocation)
-----------------------------------
The grouping value must match, byte-for-byte after normalization, what the
state's live adapter computes for ``contest_group`` at ingest time (see
``aggregation/identity.py``) — otherwise the very next sync won't recognize
the rekeyed row and will mint a duplicate anyway.

  --group-by <field>            plain Race model field
  --group-by-metadata <key>     Race.source_metadata[key]
  --group-by-compound f1,f2     "f1:f2" from two Race model fields

Per-state invocations:

    MA   --group-by-compound office_title,jurisdiction   (ma_sos: f"{office}:{district}")
    SC   --group-by-metadata vrems_election_id           (sc_vrems: electionId)
    TX   --group-by-metadata tx_election_id              (tx_goelect: election_id)
    GA   --group-by-metadata ga_public_election_id       (ga_sos: publicElectionId)
    VA   --group-by-metadata enr_slug                    (va_elect: enr_slug)

GA and VA work through the same race-level metadata mode as SC/TX because
``ga_sos/mappers.py`` and ``va_elect/mappers.py`` copy the election's
``ga_public_election_id`` / ``enr_slug`` onto every Race's ``source_metadata``.
Reading the group from the races (rather than from the parent Election's own
metadata) is what lets this command *detect* a genuine multi-id collision in
those states instead of assuming one cannot exist — the Election's own
source link is last-write-wins and cannot show it.

IMPORTANT precondition for --group-by-compound: it only converges with an
adapter's own contest_group formula when every compound field is genuinely
populated on every race in the group. A field a mapper defaults to a
placeholder when the source value is empty (e.g. MA's Race.jurisdiction
defaulting to "Statewide" for an empty district) will NOT match the adapter's
un-defaulted value. Any race with an empty constituent field is refused
outright rather than silently building a non-converging key, and the preview
prints a WARNING when a compound group contains the literal "statewide" — a
safety net for the operator, not a guarantee.

A race whose grouping value normalizes to empty is likewise refused:
``election_canonical_key(contest_group="")`` returns the *base* key, so the
race would be rekeyed/reparented straight back onto the row being replaced.
Refusals are collected per-election and reported together at the end (the run
continues through the other elections and each election's mutation is its own
transaction), then the command exits non-zero. Fix the underlying data and
re-run — the command is idempotent.

``--inherit-sole-group`` is the one sanctioned way past that refusal, and only
in the case where nothing is ambiguous: when every sibling race that *has* a
grouping value agrees on a single one, a keyless race can only belong to that
same contest, so it inherits it. VA needs this — a `results_adapter` race
ingested alongside its `va_elect` twin carries no `enr_slug`. When the siblings
span two or more groups the refusal stands regardless of the flag, because
there is then no way to tell which contest the keyless race belongs to.

DEPLOYMENT ORDER (critical, mirrors merge_duplicate_races)
----------------------------------------------------------
1. Pause the sync schedulers for the affected states.
2. Deploy the adapter + identity changes.
3. Run this command per state — without --yes first, inspect, then with --yes.
4. Resume schedulers.

Usage:
    python manage.py repair_collided_elections --state MA --group-by-compound office_title,jurisdiction
    python manage.py repair_collided_elections --state SC --group-by-metadata vrems_election_id --yes
    python manage.py repair_collided_elections --state GA --group-by-metadata ga_public_election_id --yes
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aggregation.identity import election_canonical_key
from elections.models import Election, ElectionSourceLink, Race

_GROUP_FIELDS = {"jurisdiction", "office_title"}


def _normalize(raw_value: str) -> str:
    """Match election_canonical_key's own contest_group normalization
    (aggregation/identity.py: _squash(...).lower()) so a rekeyed
    canonical_key is byte-identical to what the live adapter would compute."""
    return " ".join((raw_value or "").split()).lower()


def _swapped_race_key(stored_key: str, old_election_key: str, new_election_key: str) -> str | None:
    """Return the race key with its leading election-key segment replaced, or
    None when the stored key doesn't embed the old election key."""
    if not old_election_key or not (stored_key or "").startswith(f"{old_election_key}|"):
        return None
    return new_election_key + stored_key[len(old_election_key):]


class Command(BaseCommand):
    help = (
        "Rekey special Elections onto contest_group-suffixed canonical keys, "
        "splitting any that hold genuinely unrelated contests (issue #187)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--state", required=True, help="Two-letter state code, e.g. MA")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--group-by", choices=sorted(_GROUP_FIELDS), default=None,
            help="Race field that distinguishes the contests",
        )
        mode.add_argument(
            "--group-by-metadata", metavar="KEY", default=None,
            help="Race.source_metadata key that distinguishes the contests "
                 "(vrems_election_id for SC, tx_election_id for TX, "
                 "ga_public_election_id for GA, enr_slug for VA)",
        )
        mode.add_argument(
            "--group-by-compound", metavar="FIELD1,FIELD2", default=None,
            help="Two comma-separated Race model fields joined with ':' "
                 "(office_title,jurisdiction for MA)",
        )
        parser.add_argument(
            "--inherit-sole-group", action="store_true",
            help="When a race has no grouping value but every sibling that does agrees on a "
                 "single group, place it in that group instead of refusing the election. "
                 "Still refuses when the siblings span more than one group.",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually mutate the database. Without this flag, only prints what would happen.",
        )

    def handle(self, *args, **options):
        state = options["state"].upper()
        apply_changes = options["yes"]
        inherit_sole_group = options["inherit_sole_group"]
        key_fn, label, mode, is_empty_fn = self._resolve_grouping(options)

        stats: dict[str, int] = defaultdict(int)
        refusals: list[str] = []

        elections = (
            Election.objects.filter(state=state, election_type=Election.ElectionType.SPECIAL)
            .order_by("election_date", "pk")
        )

        for election in elections:
            races = list(election.races.all())
            if not races:
                # Nothing to derive a contest_group from. Harmless if the source
                # no longer emits this election (its key is inert); reported so
                # an operator can tell the two cases apart.
                stats["skipped_no_races"] += 1
                self.stdout.write(self.style.WARNING(
                    f"Election {election.pk} ({election.canonical_key}) has no races — "
                    "cannot derive a contest_group; left on its current key."
                ))
                continue

            values = {r.pk: ("" if is_empty_fn(r) else key_fn(r)) for r in races}
            empty_races = [r for r in races if not values[r.pk]]
            distinct = sorted({v for v in values.values() if v})

            if empty_races:
                race_ids = ", ".join(str(r.pk) for r in empty_races)
                sole_group = distinct[0] if len(distinct) == 1 else None

                if sole_group is not None and inherit_sole_group:
                    # Every sibling that HAS a grouping value agrees on one, so
                    # there is no ambiguity about where the keyless race belongs:
                    # this election describes a single contest either way. Only
                    # safe under that condition — with two or more sibling groups
                    # a keyless race genuinely cannot be placed.
                    for race in empty_races:
                        values[race.pk] = sole_group
                    stats["races_inherited_group"] += len(empty_races)
                    self.stdout.write(self.style.WARNING(
                        f"Election {election.pk} ({election.canonical_key}): race id(s) "
                        f"[{race_ids}] have no {label} value; inheriting the sole sibling "
                        f"group {sole_group!r} (--inherit-sole-group)."
                    ))
                else:
                    stats["refused"] += 1
                    if sole_group is not None:
                        reason = (
                            f"every other race agrees on the single group {sole_group!r}, so "
                            "--inherit-sole-group would place them there; re-run with that flag "
                            "if that is right for this data"
                        )
                    elif distinct:
                        reason = (
                            f"sibling races span {len(distinct)} different groups, so these races "
                            "cannot be placed — fix the missing/empty source data and re-run"
                        )
                    else:
                        reason = (
                            "no race in this election has a grouping value at all — fix the "
                            "missing/empty source data (or the --group-by-* field/key selection) "
                            "and re-run"
                        )
                    refusals.append(
                        f"Election {election.pk} ({election.canonical_key}): {label} produced an "
                        f"empty/uninformative grouping value for race id(s) [{race_ids}]"
                    )
                    self.stdout.write(self.style.ERROR(
                        f"Election {election.pk} ({election.canonical_key}): REFUSED — {label} "
                        f"produced an empty/uninformative grouping value for race id(s) "
                        f"[{race_ids}]. An empty contest_group yields the unchanged base key, so "
                        f"these races would be rekeyed straight back onto the row being replaced. "
                        f"Here {reason}."
                    ))
                    continue

            groups: dict[str, list[Race]] = {}
            for race in races:
                groups.setdefault(values[race.pk], []).append(race)

            if len(groups) == 1:
                self._rekey_in_place(
                    election, races, next(iter(groups)), label, mode,
                    apply_changes, stats, refusals,
                )
            else:
                self._split_one(election, groups, label, mode, apply_changes, stats)

        self._report(state, label, stats, refusals, apply_changes)

    def _resolve_grouping(self, options):
        """Return (key_fn, label, mode, is_empty_fn) for whichever mutually-exclusive
        --group-by* option was supplied.

        key_fn(race) -> normalized grouping key string.
        mode is one of "field", "metadata", "compound" — used to decide whether to
        print the compound-mode placeholder-default warning.
        is_empty_fn(race) -> True if this race's grouping value carries no genuine
        distinguishing information. This is checked per-race on the *constituent*
        value(s), not on key_fn's joined output: --group-by-compound's "f1:f2"
        format always contains the ':' separator, so the joined string is never
        literally "" even when both underlying fields are empty.
        """
        group_by = options.get("group_by")
        group_by_metadata = options.get("group_by_metadata")
        group_by_compound = options.get("group_by_compound")

        if group_by:
            def key_fn(race, _field=group_by):
                return _normalize(getattr(race, _field) or "")
            return key_fn, f"--group-by {group_by}", "field", (lambda race: key_fn(race) == "")

        if group_by_metadata:
            def key_fn(race, _key=group_by_metadata):
                raw_value = (race.source_metadata or {}).get(_key, "")
                return _normalize(str(raw_value or ""))
            return (
                key_fn, f"--group-by-metadata {group_by_metadata}", "metadata",
                (lambda race: key_fn(race) == ""),
            )

        fields = [f.strip() for f in group_by_compound.split(",")]
        if len(fields) != 2 or not all(fields):
            raise CommandError(
                "--group-by-compound requires exactly two comma-separated field names, "
                f"got {group_by_compound!r}"
            )
        field1, field2 = fields
        unknown = [f for f in (field1, field2) if f not in _GROUP_FIELDS]
        if unknown:
            raise CommandError(
                f"--group-by-compound: unknown field(s) {unknown} — must be one of "
                f"{sorted(_GROUP_FIELDS)}, got {group_by_compound!r}"
            )

        def key_fn(race, _f1=field1, _f2=field2):
            raw_value = f"{getattr(race, _f1) or ''}:{getattr(race, _f2) or ''}"
            return _normalize(raw_value)

        def is_empty_fn(race, _f1=field1, _f2=field2):
            return (
                _normalize(getattr(race, _f1) or "") == ""
                or _normalize(getattr(race, _f2) or "") == ""
            )

        return key_fn, f"--group-by-compound {group_by_compound}", "compound", is_empty_fn

    # ------------------------------------------------------------------ #
    # Path 1: one contest -> rekey the row in place
    # ------------------------------------------------------------------ #
    def _rekey_in_place(
        self, election: Election, races: list[Race], group_value: str, label: str,
        mode: str, apply_changes: bool, stats, refusals: list[str],
    ) -> None:
        old_key = election.canonical_key or ""
        new_key = election_canonical_key(
            election.state, election.election_type, election.election_date,
            election.jurisdiction_level, contest_group=group_value,
        )
        if old_key == new_key:
            stats["already_converged"] += 1
            return

        self.stdout.write(
            f"Election {election.pk} ({election.name!r}): single contest by {label} — "
            f"rekey {old_key} -> {new_key} ({len(races)} race(s))"
        )
        self._warn_on_placeholder(mode, group_value)

        clash = Election.objects.filter(canonical_key=new_key).exclude(pk=election.pk).first()
        if clash is not None:
            stats["election_key_conflicts"] += 1
            refusals.append(
                f"Election {election.pk} ({old_key}) cannot take key {new_key} — already held "
                f"by Election {clash.pk}"
            )
            self.stdout.write(self.style.ERROR(
                f"  REFUSED — key {new_key} is already held by Election {clash.pk}. Two rows now "
                "describe the same contest (a duplicate the live sync likely already minted); "
                "merge them by hand, then re-run."
            ))
            return

        if not apply_changes:
            stats["would_rekey_in_place"] += 1
            self._rekey_races(races, old_key, new_key, apply_changes=False, stats=stats)
            self.stdout.write(self.style.WARNING("  (dry run — pass --yes to apply)"))
            return

        with transaction.atomic():
            election.canonical_key = new_key
            election.save(update_fields=["canonical_key"])
            self._rekey_races(races, old_key, new_key, apply_changes=True, stats=stats)

        stats["rekeyed_in_place"] += 1
        self.stdout.write(self.style.SUCCESS(f"  done — Election {election.pk} rekeyed in place"))

    # ------------------------------------------------------------------ #
    # Path 2: several contests -> split into one Election per contest
    # ------------------------------------------------------------------ #
    def _split_one(
        self, election: Election, groups: dict[str, list[Race]], label: str,
        mode: str, apply_changes: bool, stats,
    ) -> None:
        old_key = election.canonical_key or ""
        self.stdout.write(
            f"Election {election.pk} ({election.name!r}, {old_key}): "
            f"splitting into {len(groups)} groups by {label}"
        )

        original_links = list(election.source_links_rel.all()) if apply_changes else []

        with transaction.atomic():
            for group_value, group_races in groups.items():
                new_key = election_canonical_key(
                    election.state, election.election_type, election.election_date,
                    election.jurisdiction_level, contest_group=group_value,
                )
                sample = group_races[0]
                titles = ", ".join(sorted({r.office_title for r in group_races}))
                self.stdout.write(
                    f"  group={group_value!r} -> canonical_key={new_key} "
                    f"({len(group_races)} race(s): {titles})"
                )
                self._warn_on_placeholder(mode, group_value)
                if not apply_changes:
                    self._rekey_races(
                        group_races, old_key, new_key, apply_changes=False, stats=stats,
                    )
                    continue

                group_sources = sorted({r.source for r in group_races if r.source})

                new_election, _created = Election.objects.get_or_create(
                    canonical_key=new_key,
                    defaults={
                        "state": election.state,
                        "election_type": election.election_type,
                        "election_date": election.election_date,
                        "jurisdiction_level": election.jurisdiction_level,
                        "name": f"{election.name} ({sample.jurisdiction or sample.office_title})",
                        "status": election.status,
                        "last_synced_at": election.last_synced_at,
                        "source_metadata": {"repaired_from_election_id": election.pk},
                        "contributing_sources": group_sources,
                    },
                )
                self._rekey_races(
                    group_races, old_key, new_key, apply_changes=True, stats=stats,
                    new_election=new_election,
                )

                # Reparent provenance: duplicate each original source link onto every
                # split child whose group actually contains a race built from that
                # source. A link whose source matches no group's races has nothing to
                # attach to and is not carried forward.
                for link in original_links:
                    if link.source in group_sources:
                        ElectionSourceLink.objects.update_or_create(
                            election=new_election, source=link.source,
                            defaults={
                                "source_id": link.source_id,
                                "results_url": link.results_url,
                                "last_synced_at": link.last_synced_at,
                            },
                        )

            if apply_changes:
                ElectionSourceLink.objects.filter(election=election).delete()
                election.delete()

        if apply_changes:
            stats["split"] += 1
            self.stdout.write(self.style.SUCCESS(f"  done — original Election {election.pk} removed"))
        else:
            stats["would_split"] += 1
            self.stdout.write(self.style.WARNING("  (dry run — pass --yes to apply)"))

    # ------------------------------------------------------------------ #
    # Shared: race canonical_key prefix swap (+ optional reparent)
    # ------------------------------------------------------------------ #
    def _rekey_races(
        self, races: list[Race], old_election_key: str, new_election_key: str,
        apply_changes: bool, stats, new_election: Election | None = None,
    ) -> None:
        """Rewrite each race's canonical_key so it embeds new_election_key, and
        (when splitting) reparent it. A race's key embeds its election's key, so
        leaving it stale would make the next sync mint a duplicate race under the
        correctly-keyed election."""
        for race in races:
            update_fields = []
            if new_election is not None and race.election_id != new_election.pk:
                race.election = new_election
                update_fields.append("election")

            new_race_key = _swapped_race_key(race.canonical_key or "", old_election_key, new_election_key)

            if new_race_key is None:
                stats["races_key_unrecognized"] += 1
                self.stdout.write(self.style.WARNING(
                    f"    race {race.pk}: canonical_key {race.canonical_key!r} does not embed "
                    f"the election key {old_election_key!r} — left unchanged. The next sync will "
                    "compute a key from the new election key and may create a duplicate race; "
                    "check this row by hand."
                ))
            elif new_race_key == race.canonical_key:
                stats["races_key_already_current"] += 1
            else:
                clash = Race.objects.filter(canonical_key=new_race_key).exclude(pk=race.pk).first()
                if clash is not None:
                    stats["races_key_conflicts"] += 1
                    self.stdout.write(self.style.ERROR(
                        f"    race {race.pk}: target key {new_race_key} already held by race "
                        f"{clash.pk} — left unchanged and flagged for review."
                    ))
                    if apply_changes:
                        race.match_confidence = Race.MatchConfidence.FLAGGED
                        update_fields.append("match_confidence")
                else:
                    stats["races_rekeyed"] += 1
                    race.canonical_key = new_race_key
                    update_fields.append("canonical_key")

            if apply_changes and update_fields:
                race.save(update_fields=update_fields)

    def _warn_on_placeholder(self, mode: str, group_value: str) -> None:
        if mode == "compound" and "statewide" in group_value:
            self.stdout.write(self.style.WARNING(
                f"  WARNING: group={group_value!r} contains the literal 'statewide' — "
                "this may be a mapper-applied placeholder default (e.g. an empty district "
                "defaulting to jurisdiction='Statewide') rather than a value genuinely "
                "present in the source data. --group-by-compound only converges with the "
                "live adapter's own contest_group when every compound field is genuinely "
                "populated on every race in this group — verify before running with --yes."
            ))

    # ------------------------------------------------------------------ #
    # Summary + convergence invariant
    # ------------------------------------------------------------------ #
    def _report(self, state: str, label: str, stats, refusals: list[str], apply_changes: bool) -> None:
        mode_label = "APPLY" if apply_changes else "DRY RUN"
        summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "nothing to do"
        self.stdout.write(f"[{mode_label}] {state} ({label}): {summary}")

        problems = list(refusals)

        if apply_changes:
            # Convergence invariant: once the adapter emits contest_group, any
            # special election still on a bare (suffix-less) key will be missed by
            # the next sync, which then mints a duplicate. Elections with no races
            # are exempt — nothing can derive their group, and the source no longer
            # drives them.
            stragglers = [
                e for e in Election.objects.filter(
                    state=state, election_type=Election.ElectionType.SPECIAL,
                ).order_by("pk")
                if "|" not in (e.canonical_key or "") and e.races.exists()
            ]
            for straggler in stragglers:
                problems.append(
                    f"Election {straggler.pk} ({straggler.canonical_key}) still has no "
                    "contest_group suffix"
                )

        if stats.get("races_key_conflicts"):
            problems.append(
                f"{stats['races_key_conflicts']} race(s) could not take their new canonical_key "
                "(target already held) — flagged for review"
            )
        if stats.get("races_key_unrecognized"):
            problems.append(
                f"{stats['races_key_unrecognized']} race(s) had a canonical_key that does not "
                "embed their election's key — left unchanged"
            )

        if problems:
            raise CommandError(
                f"{state}: {len(problems)} unresolved item(s) — the next sync would create "
                "duplicates for these. Fix and re-run (this command is idempotent):\n  "
                + "\n  ".join(problems)
            )

        self.stdout.write(self.style.SUCCESS(
            f"{state}: every special Election with races now carries a contest_group-suffixed "
            "canonical_key matching what the live adapter computes."
            if apply_changes else
            f"{state}: dry run complete — no changes written."
        ))
