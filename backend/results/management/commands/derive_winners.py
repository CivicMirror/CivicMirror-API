"""
Backfill is_winner on certified results where the source didn't set it (results/winners.py).

Usage:
    python manage.py derive_winners --dry-run              # report only; writes nothing
    python manage.py derive_winners --dry-run --state MA --samples 10
    python manage.py derive_winners [--state NC]           # apply
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from elections.models import Race
from results.winners import apply_derivation, derive_winners


class Command(BaseCommand):
    help = "Derive is_winner for certified candidate races (dry-run by default with --dry-run)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report outcomes without writing.")
        parser.add_argument("--state", default=None)
        parser.add_argument("--samples", type=int, default=0, help="Print N sample derived races per state.")

    def handle(self, *args, **options):
        races = (
            Race.objects.filter(certification_status=Race.CertificationStatus.RESULTS_CERTIFIED)
            .select_related("election")
            .prefetch_related("official_results__candidate")
            .order_by("election__state", "pk")
        )
        if options["state"]:
            races = races.filter(election__state__iexact=options["state"])

        outcomes = Counter()
        by_state = defaultdict(Counter)
        samples = defaultdict(list)
        winner_rows = 0
        for race in races.iterator(chunk_size=500):
            if options["dry_run"]:
                rows = list(race.official_results.all())
                derivation = derive_winners(race, rows)
            else:
                with transaction.atomic():
                    # An import may have changed source flags since the outer query's prefetch.
                    race = Race.objects.select_for_update(of=("self",)).select_related("election").get(pk=race.pk)
                    rows = list(race.official_results.select_related("candidate"))
                    derivation = derive_winners(race, rows)
                    apply_derivation(race, derivation)  # also clears stale derived flags on skips
            outcomes[derivation.outcome] += 1
            by_state[race.election.state][derivation.outcome] += 1
            if derivation.outcome == "derived":
                winner_rows += len(derivation.winner_row_ids)
                if len(samples[race.election.state]) < options["samples"]:
                    by_id = {r.pk: r for r in rows}
                    names = ", ".join(
                        f"{by_id[i].candidate.name} ({by_id[i].vote_count})" for i in derivation.winner_row_ids
                    )
                    samples[race.election.state].append(
                        f"{race.election.election_date} {race.office_title[:50]}"
                        f"{' [' + race.party + ']' if race.party else ''} -> {names}"
                    )

        self.stdout.write(f"Certified races examined: {sum(outcomes.values())}")
        for outcome, count in outcomes.most_common():
            self.stdout.write(f"  {outcome:32} {count}")
        self.stdout.write(f"Winner rows {'that would be' if options['dry_run'] else ''} marked: {winner_rows}")
        self.stdout.write("Derived by state: " + ", ".join(
            f"{state} {c['derived']}" for state, c in sorted(by_state.items()) if c["derived"]
        ))
        for state, lines in sorted(samples.items()):
            self.stdout.write(f"-- {state} samples:")
            for line in lines:
                self.stdout.write(f"   {line}")
        if options["dry_run"]:
            self.stdout.write("[DRY RUN] nothing written.")
