"""
Split Election rows that collapsed unrelated same-day special elections
before contest_group existed on election_canonical_key. See issue #187.

Usage:
    python manage.py repair_collided_elections --state MA --group-by jurisdiction
    python manage.py repair_collided_elections --state MA --group-by jurisdiction --yes
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from aggregation.identity import election_canonical_key
from elections.models import Election, ElectionSourceLink, Race

_GROUP_FIELDS = {"jurisdiction", "office_title"}


class Command(BaseCommand):
    help = "Split Election rows whose Races span more than one distinct contest (issue #187)."

    def add_arguments(self, parser):
        parser.add_argument("--state", required=True, help="Two-letter state code, e.g. MA")
        parser.add_argument(
            "--group-by", required=True, choices=sorted(_GROUP_FIELDS),
            help="Race field that distinguishes the collided contests",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually mutate the database. Without this flag, only prints what would happen.",
        )

    def handle(self, *args, **options):
        state = options["state"]
        group_by = options["group_by"]
        apply_changes = options["yes"]

        collided = (
            Election.objects.filter(state=state, election_type=Election.ElectionType.SPECIAL)
            .annotate(n_groups=Count(f"races__{group_by}", distinct=True))
            .filter(n_groups__gt=1)
            .order_by("election_date")
        )

        if not collided.exists():
            self.stdout.write(self.style.SUCCESS(f"No collided special elections found for {state}."))
            return

        for election in collided:
            self._split_one(election, group_by, apply_changes)

    def _split_one(self, election: Election, group_by: str, apply_changes: bool) -> None:
        races = list(election.races.all())
        groups: dict[str, list[Race]] = {}
        for race in races:
            raw_value = getattr(race, group_by) or ""
            key = " ".join(raw_value.split()).lower()
            groups.setdefault(key, []).append(race)

        if len(groups) <= 1:
            return  # annotate() can be stale mid-loop after a prior split; skip if already fixed

        self.stdout.write(
            f"Election {election.pk} ({election.name!r}, {election.canonical_key}): "
            f"splitting into {len(groups)} groups by {group_by}"
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
