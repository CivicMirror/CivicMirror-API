"""
Split Election rows that collapsed unrelated same-day special elections
before contest_group existed on election_canonical_key. See issue #187.

The grouping key used here must match, byte-for-byte after normalization,
what the state's live adapter computes for `contest_group` at ingest time
(aggregation/identity.py's election_canonical_key) — otherwise the very
next scheduled sync after repair won't recognize the repaired row and will
mint a duplicate Election. Three grouping modes are supported, one per
invocation:

  --group-by <field>            plain Race model field (NC: office_title)
  --group-by-metadata <key>     Race.source_metadata[key] (SC: vrems_election_id,
                                 TX: tx_election_id)
  --group-by-compound f1,f2     "f1:f2" from two Race model fields (MA:
                                 office_title,jurisdiction, matching ma_sos's
                                 own f"{office}:{district}" join)

IMPORTANT precondition for --group-by-compound: it only converges with an
adapter's own contest_group formula when every compound field is genuinely
populated (non-empty) on every race in the group. A field that a mapper
defaults to a placeholder when the source value is empty (e.g. MA's
Race.jurisdiction defaulting to "Statewide" when ma_sos's raw `district` is
"") will NOT match the adapter's own un-defaulted value, and the very next
sync will mint a duplicate Election instead of updating the repaired row.
Any race with a genuinely empty compound field is refused outright
(CommandError, see below) rather than silently building a non-converging
key. The dry-run preview additionally prints a WARNING line if a compound
group's value contains the literal "statewide" — a heuristic safety net for
an operator reviewing output before --yes, not a hard guarantee (it will not
catch every possible placeholder default).

A race whose grouping key normalizes to empty is refused, not silently
processed: election_canonical_key(contest_group="") returns the *base* key,
unchanged from the original collided Election's own canonical_key, so
get_or_create() would reparent that race back onto the very Election being
split, which is then deleted (CASCADE) once the split completes — silently
destroying the race. Fix the underlying data (missing metadata key / empty
field) and re-run.

Do NOT run this command for GA or VA: every one of their "collided" special
elections (27 for GA, 4 for VA) is a legitimate single ballot bundling
multiple districts under one public_id/enr_slug, not a genuine collision —
the multi-jurisdiction + type=special heuristic false-positives on them.
Splitting these would shatter real ballots into fake separate Elections.
This is enforced in code (handle() raises CommandError immediately for
state=GA/VA) — there is no override flag. See issue #187 / Task 8.

Usage:
    python manage.py repair_collided_elections --state MA --group-by-compound office_title,jurisdiction
    python manage.py repair_collided_elections --state SC --group-by-metadata vrems_election_id --yes
    python manage.py repair_collided_elections --state NC --group-by office_title --yes
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aggregation.identity import election_canonical_key
from elections.models import Election, ElectionSourceLink, Race

_GROUP_FIELDS = {"jurisdiction", "office_title"}


def _normalize(raw_value: str) -> str:
    """Match election_canonical_key's own contest_group normalization
    (aggregation/identity.py: _squash(...).lower()) so a repaired
    canonical_key is byte-identical to what the live adapter would compute."""
    return " ".join((raw_value or "").split()).lower()


class Command(BaseCommand):
    help = "Split Election rows whose Races span more than one distinct contest (issue #187)."

    def add_arguments(self, parser):
        parser.add_argument("--state", required=True, help="Two-letter state code, e.g. MA")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--group-by", choices=sorted(_GROUP_FIELDS), default=None,
            help="Race field that distinguishes the collided contests",
        )
        mode.add_argument(
            "--group-by-metadata", metavar="KEY", default=None,
            help="Race.source_metadata key that distinguishes the collided contests "
                 "(e.g. vrems_election_id for SC, tx_election_id for TX)",
        )
        mode.add_argument(
            "--group-by-compound", metavar="FIELD1,FIELD2", default=None,
            help="Two comma-separated Race model fields joined with ':' "
                 "(e.g. office_title,jurisdiction for MA)",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually mutate the database. Without this flag, only prints what would happen.",
        )

    def handle(self, *args, **options):
        state = options["state"]
        if state.upper() in {"GA", "VA"}:
            raise CommandError(
                f"Refusing to run repair for state={state!r}: production investigation found "
                "no genuine grouping-key collisions in GA or VA — every one of their "
                "'collided' special elections (27 for GA, 4 for VA) is a single legitimate "
                "ballot bundling multiple districts under one public_id/enr_slug, not a real "
                "collision. Splitting these would shatter real ballots into fake separate "
                "Elections. See issue #187 / Task 8 for the production evidence. This is a "
                "hard exclusion, not a flag to bypass — a genuine future GA/VA collision would "
                "need its own reviewed code change, not a runtime override."
            )
        apply_changes = options["yes"]
        key_fn, label, mode, is_empty_fn = self._resolve_grouping(options)

        collided = (
            Election.objects.filter(state=state, election_type=Election.ElectionType.SPECIAL)
            .order_by("election_date")
        )

        found_any = False
        for election in collided:
            races = list(election.races.all())
            if len({key_fn(r) for r in races}) <= 1:
                continue
            found_any = True
            self._split_one(election, key_fn, label, mode, is_empty_fn, apply_changes)

        if not found_any:
            self.stdout.write(self.style.SUCCESS(f"No collided special elections found for {state}."))

    def _resolve_grouping(self, options):
        """Return (key_fn, label, mode, is_empty_fn) for whichever mutually-exclusive
        --group-by* option was supplied.

        key_fn(race) -> normalized grouping key string.
        mode is one of "field", "metadata", "compound" — used by _split_one to decide
        whether to print the compound-mode placeholder-default warning (Finding #3,
        issue #187 / Task 8 review).
        is_empty_fn(race) -> True if this race's grouping value carries no genuine
        distinguishing information and must never be used to build a group (Finding
        #1, issue #187 / Task 8 review). This is checked per-race on the *constituent*
        value(s), not on key_fn's joined output: --group-by-compound's "f1:f2" format
        always contains the ':' separator, so the joined string is never literally ""
        even when both underlying fields are empty — checking the joined string alone
        would miss that case.
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

    def _split_one(
        self, election: Election, key_fn, label: str, mode: str, is_empty_fn, apply_changes: bool
    ) -> None:
        races = list(election.races.all())
        groups: dict[str, list[Race]] = {}
        for race in races:
            groups.setdefault(key_fn(race), []).append(race)

        if len(groups) <= 1:
            return  # stale mid-loop read after a prior split; skip if already fixed

        empty_races = [r for r in races if is_empty_fn(r)]
        if empty_races:
            race_ids = ", ".join(str(r.pk) for r in empty_races)
            raise CommandError(
                f"Election {election.pk} ({election.canonical_key}): {label} produced an "
                f"empty/uninformative grouping value for race id(s) [{race_ids}]. Refusing to "
                "split this election. For --group-by/--group-by-metadata, an empty key's "
                "canonical_key equals the ORIGINAL election's own canonical_key, so "
                "get_or_create() would silently reparent that race back onto the original "
                "Election, which then gets CASCADE-deleted when the split completes below, "
                "destroying it. For --group-by-compound, an empty constituent field means the "
                "built key cannot converge with the live adapter's own contest_group (see "
                "module docstring). Fix the missing/empty source data (or the --group-by-* "
                "field/key selection) for these races and re-run. See Finding #1, issue #187 / "
                "Task 8."
            )

        self.stdout.write(
            f"Election {election.pk} ({election.name!r}, {election.canonical_key}): "
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
                if mode == "compound" and "statewide" in group_value:
                    self.stdout.write(self.style.WARNING(
                        f"  WARNING: group={group_value!r} contains the literal 'statewide' — "
                        "this may be a mapper-applied placeholder default (e.g. an empty "
                        "district defaulting to jurisdiction='Statewide') rather than a value "
                        "genuinely present in the source data. --group-by-compound only "
                        "converges with the live adapter's own contest_group when every "
                        "compound field is genuinely populated on every race in this group — "
                        "verify this group's races before running with --yes."
                    ))
                if not apply_changes:
                    continue

                group_sources = sorted({r.source for r in group_races if r.source})

                new_election, created = Election.objects.get_or_create(
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
                for race in group_races:
                    race.election = new_election
                    race.save(update_fields=["election"])

                # Reparent provenance: duplicate each original source link onto every
                # split child whose group actually contains a race built from that
                # source. A link whose source matches no group's races has nothing to
                # attach to and is not carried forward. See finding #1, issue #187.
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
            self.stdout.write(self.style.SUCCESS(f"  done — original Election {election.pk} removed"))
        else:
            self.stdout.write(self.style.WARNING("  (dry run — pass --yes to apply)"))
