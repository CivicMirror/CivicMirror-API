"""Report source-evidenced party assignments; opt in to metadata-only application."""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from elections.models import Race
from results.parties import SUPPORTED_STATES, apply_party_plan, plan_party_updates


class Command(BaseCommand):
    help = "Report party assignments for results-bootstrap races; writes only with --apply."

    def add_arguments(self, parser):
        parser.add_argument("--state", choices=sorted(SUPPORTED_STATES))
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        query = Race.objects.filter(source="results_adapter", race_type="candidate",
                                    election__state__in=SUPPORTED_STATES).order_by("pk")
        if options["state"]:
            query = query.filter(election__state=options["state"])
        plans = []
        for pk in query.values_list("pk", flat=True).iterator():
            with transaction.atomic():
                race_query = Race.objects.select_related("election")
                if options["apply"]:
                    race_query = race_query.select_for_update(of=("self",))
                race = race_query.get(pk=pk)
                candidates = list(race.candidates.order_by("pk"))
                rows = list(race.official_results.order_by("pk"))
                plan = plan_party_updates(race, candidates, rows)
                if options["apply"]:
                    apply_party_plan(race, candidates, plan)
                plans.append(plan)
        self.stdout.write(json.dumps({"dry_run": not options["apply"], "races": plans}, indent=2))
