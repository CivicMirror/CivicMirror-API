"""
Re-derive geography_scope for races bootstrapped from results feeds.

Those races were created with a hard-coded geography_scope="statewide", so county, city and
school-board contests were all labeled statewide. This re-infers the scope from the office title
(elections.geography.infer_geography_scope). Only rows that still carry the old default are
touched: source=results_adapter and geography_scope="statewide".

Usage:
    python manage.py backfill_geography_scope --dry-run
    python manage.py backfill_geography_scope [--state NC]
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from elections.geography import infer_geography_scope
from elections.models import Race


class Command(BaseCommand):
    help = "Re-infer geography_scope for results-bootstrapped races still marked statewide"

    def add_arguments(self, parser):
        parser.add_argument("--state", default=None, help="Limit to one state (e.g. NC).")
        parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")

    def handle(self, *args, **options):
        races = Race.objects.filter(source=Race.Source.RESULTS_ADAPTER, geography_scope="statewide")
        if options["state"]:
            races = races.filter(election__state__iexact=options["state"])

        changes: dict[str, list[int]] = {}
        outcome = Counter()
        for pk, title in races.values_list("pk", "office_title").iterator():
            scope = infer_geography_scope(title)
            outcome[scope or "(blank: unknown)"] += 1
            if scope != "statewide":
                changes.setdefault(scope, []).append(pk)

        for scope, count in outcome.most_common():
            self.stdout.write(f"  {scope:18} {count}")
        total = sum(len(pks) for pks in changes.values())
        if options["dry_run"]:
            self.stdout.write(f"[DRY RUN] would update {total} of {sum(outcome.values())} race(s).")
            return
        with transaction.atomic():
            for scope, pks in changes.items():
                for start in range(0, len(pks), 1000):
                    Race.objects.filter(pk__in=pks[start:start + 1000]).update(geography_scope=scope)
        self.stdout.write(self.style.SUCCESS(f"Updated {total} of {sum(outcome.values())} race(s)."))
