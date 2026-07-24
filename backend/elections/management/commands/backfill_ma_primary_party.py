"""
Delete stale MA primary Races created before the per-party discovery fix
(issue #105), so the next ma_sos sync recreates them correctly split by party.

WHY THIS EXISTS
---------------
Before the fix, ma_sos discovery only queried the generic "Primaries" stage,
which returns a single election_id whose CSV bundles every party's primary
candidates for an office into one combined Race with ``Candidate.party ==
""`` for all of them (e.g. Race 10000 in the 2026 MA State Representative
5th Essex special — Democratic and Republican candidates on one ballot).

Discovery now also queries per-party stage slugs (Democratic, Republican,
...), which both supplies the party label and — via
``mappers.contest_variant_key`` — splits each party's primary into its own
Race. But that only takes effect for *newly created* Races: re-running sync
does not retroactively split an already-merged Race, because its stored
canonical_key has no party variant to recompute against (unlike
merge_duplicate_races, there is no "split" operation, only "merge"). The
merged Race needs to be removed so a fresh sync creates its per-party
replacements.

SCOPE
-----
Targets ma_sos-sourced primary Races where at least one candidate has a
blank party — the fingerprint of the pre-fix merged-CSV behavior. Doesn't
touch general-election Races (party is populated from the CSV header row
there) or primaries where every candidate already has a party (already
correct, or a single-party primary the old code happened to get right).

DEPLOYMENT ORDER
-----------------
1. Deploy the mappers.py/tasks.py changes from issue #105.
2. Run this command (``--dry-run`` first).
3. Re-run sync_ma_elections (or wait for the next scheduled run) so the
   deleted races are recreated, correctly split by party.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from elections.models import Election, Race

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Delete stale ma_sos MA primary Races that predate the per-party "
        "discovery fix (issue #105), identified by candidates with a blank "
        "party. Re-run sync_ma_elections afterward to recreate them split "
        "by party."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview what would be deleted without writing any changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        races = (
            Race.objects.filter(
                election__state="MA",
                election__election_type=Election.ElectionType.PRIMARY,
                source=Race.Source.MA_SOS,
            )
            .filter(candidates__party="")
            .distinct()
            .select_related("election")
        )

        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(f"[{mode}] scanning MA primary races for the pre-fix merged-party fingerprint...")

        count = 0
        for race in races:
            blank_party_names = list(
                race.candidates.filter(party="").values_list("name", flat=True)
            )
            self.stdout.write(
                f"  race={race.pk} election={race.election_id} "
                f"office={race.office_title!r} district={race.jurisdiction!r} "
                f"blank_party_candidates={blank_party_names}"
            )
            count += 1
            if not dry_run:
                with transaction.atomic():
                    race.delete()

        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY RUN] would delete {count} race(s). Re-run with --apply-equivalent (omit --dry-run) to delete."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[APPLY] deleted {count} race(s)."))
            self.stdout.write(
                "  Re-run sync_ma_elections (or wait for the next scheduled sync) "
                "to recreate these races split by party."
            )
