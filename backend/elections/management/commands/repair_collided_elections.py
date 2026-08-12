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

Do NOT run this command for GA or VA: every one of their "collided" special
elections (27 for GA, 4 for VA) is a legitimate single ballot bundling
multiple districts under one public_id/enr_slug, not a genuine collision —
the multi-jurisdiction + type=special heuristic false-positives on them.
Splitting these would shatter real ballots into fake separate Elections.
See issue #187 / Task 8.

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
        apply_changes = options["yes"]
        key_fn, label = self._resolve_grouping(options)

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
            self._split_one(election, key_fn, label, apply_changes)

        if not found_any:
            self.stdout.write(self.style.SUCCESS(f"No collided special elections found for {state}."))

    def _resolve_grouping(self, options):
        """Return (key_fn, label) for whichever mutually-exclusive --group-by*
        option was supplied. key_fn(race) -> normalized grouping key string."""
        group_by = options.get("group_by")
        group_by_metadata = options.get("group_by_metadata")
        group_by_compound = options.get("group_by_compound")

        if group_by:
            return (lambda race: _normalize(getattr(race, group_by) or "")), f"--group-by {group_by}"

        if group_by_metadata:
            def key_fn(race, _key=group_by_metadata):
                raw_value = (race.source_metadata or {}).get(_key, "")
                return _normalize(str(raw_value or ""))
            return key_fn, f"--group-by-metadata {group_by_metadata}"

        fields = [f.strip() for f in group_by_compound.split(",")]
        if len(fields) != 2 or not all(fields):
            raise CommandError(
                "--group-by-compound requires exactly two comma-separated field names, "
                f"got {group_by_compound!r}"
            )
        field1, field2 = fields

        def key_fn(race, _f1=field1, _f2=field2):
            raw_value = f"{getattr(race, _f1) or ''}:{getattr(race, _f2) or ''}"
            return _normalize(raw_value)

        return key_fn, f"--group-by-compound {group_by_compound}"

    def _split_one(self, election: Election, key_fn, label: str, apply_changes: bool) -> None:
        races = list(election.races.all())
        groups: dict[str, list[Race]] = {}
        for race in races:
            groups.setdefault(key_fn(race), []).append(race)

        if len(groups) <= 1:
            return  # stale mid-loop read after a prior split; skip if already fixed

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
