"""
Undo certification that was applied to an election that has not been held yet.

Two defects produced this state in production (see
docs/2026-11-02-midterm-poll-triage.md):

  * results/tasks.py flipped a race to results_certified/archived whenever every
    matched row carried result_type="official", with no check that election day
    had passed. 13 adapters stamp "official" unconditionally. Illinois' 141
    Nov 3, 2026 races ended up archived + certified, and the election with them.
  * results/adapters/mo.py pinned its source URL to the 2024 general election
    and ignored election_date, so certified 2024 rows (President, U.S. Senator,
    Governor, Lieutenant Governor) were written under Missouri's 2026 record.

Both are now guarded in code, but the rows they already wrote persist. This
command finds every unheld election carrying certified state and reverts it:
derived winner flags, certified_at stamps, race status, election status, and —
only with --delete-results — the OfficialResult rows of those races.

Deploy the guards BEFORE running this. Cleaning first just gets re-polluted on
the next ingestion run.

Previews by default; --apply writes. Wrong-cycle data (Missouri) needs
--delete-results, because restatusing leaves 2024 vote counts attached to 2026
races. Elections whose races should not exist at all (Missouri has no 2026
Governor or U.S. Senate race) are reported under "races" for manual delisting —
this command never deletes races or candidates.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.utils import timezone

from elections.models import Election, Race
from results.models import OfficialResult
from results.winners import clear_derived_winners


def _premature_elections(election_ids=None, states=None):
    """Unheld elections (election_date >= today) carrying any certified state."""
    today = timezone.localdate()
    qs = Election.objects.filter(election_date__gte=today)
    if election_ids:
        qs = qs.filter(pk__in=election_ids)
    if states:
        qs = qs.filter(state__in=states)
    certified_race = Race.objects.filter(
        election=models.OuterRef("pk"),
    ).filter(
        models.Q(certification_status=Race.CertificationStatus.RESULTS_CERTIFIED)
        | models.Q(race_status=Race.RaceStatus.ARCHIVED)
    )
    stamped_row = OfficialResult.objects.filter(
        race__election=models.OuterRef("pk"), certified_at__isnull=False
    )
    return (
        qs.filter(
            models.Q(status__in=Election.TERMINAL_STATUSES)
            | models.Q(models.Exists(certified_race))
            | models.Q(models.Exists(stamped_row))
        )
        .order_by("state", "election_date", "pk")
    )


def _election_target_status(election) -> str:
    """
    Where an unheld election belongs.

    Polling day itself becomes results_pending rather than active: poll_pending_results
    only queues RESULTS_PENDING elections, so this keeps the election certifiable from
    tomorrow without depending on a per-state sync to restamp its status. It is also in
    poll_upcoming_results' allowed statuses, so today's polling still happens.
    """
    if election.election_date > timezone.localdate():
        return Election.Status.UPCOMING
    return Election.Status.RESULTS_PENDING


def build_plan(election_ids=None, states=None, delete_results=False) -> dict:
    """Inventory what needs reverting. Reads only; safe to run against production."""
    elections = []
    for election in _premature_elections(election_ids, states):
        races = []
        for race in Race.objects.filter(election=election).order_by("pk"):
            needs_status = (
                race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED
                or race.race_status == Race.RaceStatus.ARCHIVED
            )
            rows = OfficialResult.objects.filter(race=race)
            row_count = rows.count()
            stamped = rows.filter(certified_at__isnull=False).count()
            derived = bool((race.source_metadata or {}).get("winners_derived"))
            # Only races actually carrying premature certification are touched — including
            # by --delete-results, so a mixed election cannot lose legitimate rows.
            if not (needs_status or stamped or derived):
                continue
            races.append(
                {
                    "race_id": race.pk,
                    "office_title": race.office_title,
                    "certification_status": race.certification_status,
                    "race_status": race.race_status,
                    "result_rows": row_count,
                    "certified_at_stamps": stamped,
                    "derived_winners": derived,
                }
            )
        if not races and election.status not in Election.TERMINAL_STATUSES:
            continue
        elections.append(
            {
                "election_id": election.pk,
                "state": election.state or None,
                "name": election.name,
                "election_date": election.election_date.isoformat(),
                "status": election.status,
                "target_status": _election_target_status(election),
                "races": races,
            }
        )
    return {
        "generated_at": timezone.now().isoformat(),
        "today": timezone.localdate().isoformat(),
        "delete_results": delete_results,
        "applied": False,
        "elections": elections,
        "totals": {
            "elections": len(elections),
            "races": sum(len(e["races"]) for e in elections),
            "result_rows": sum(r["result_rows"] for e in elections for r in e["races"]),
        },
    }


def apply_plan(plan: dict) -> dict:
    """Revert everything the plan lists, in one transaction."""
    delete_results = plan["delete_results"]
    deleted_rows = 0
    with transaction.atomic():
        for entry in plan["elections"]:
            election = Election.objects.select_for_update().get(pk=entry["election_id"])
            for race_entry in entry["races"]:
                race = Race.objects.select_for_update().get(pk=race_entry["race_id"])
                # Retire our own derived winner flags first; source-set flags are left alone,
                # which is exactly what clear_derived_winners guarantees.
                clear_derived_winners(race)
                rows = OfficialResult.objects.filter(race=race)
                if delete_results:
                    deleted_rows += rows.count()
                    rows.delete()
                    race.certification_status = Race.CertificationStatus.UPCOMING
                else:
                    # Rows stay, but nothing about them is certified yet.
                    rows.filter(certified_at__isnull=False).update(certified_at=None)
                    race.certification_status = Race.CertificationStatus.RESULTS_PENDING
                if race.race_status == Race.RaceStatus.ARCHIVED:
                    race.race_status = Race.RaceStatus.ACTIVE
                race.save(update_fields=["certification_status", "race_status"])
            if election.status in Election.TERMINAL_STATUSES:
                election.status = entry["target_status"]
                election.save(update_fields=["status"])
    return {**plan, "applied": True, "deleted_result_rows": deleted_rows}


class Command(BaseCommand):
    help = (
        "Revert certification applied to elections that have not been held yet. "
        "Previews by default; --apply writes. Deploy the tasks.py/mo.py guards first."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--election-id",
            dest="election_ids",
            type=int,
            action="append",
            default=None,
            help="Limit to this election; repeatable. Default: every unheld election affected.",
        )
        parser.add_argument(
            "--state",
            dest="states",
            action="append",
            default=None,
            help="Limit to this two-letter state; repeatable (e.g. --state MO --state IL).",
        )
        parser.add_argument(
            "--delete-results",
            action="store_true",
            help=(
                "Also delete the OfficialResult rows of the affected races (not of every race "
                "in the election). Required for wrong-cycle data such as Missouri's 2024 rows; "
                "without it the rows are kept and only un-certified."
            ),
        )
        parser.add_argument("--report", help="Write the full JSON report here as well as to stdout.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Preview only (the default).")
        mode.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        states = [s.upper() for s in (options["states"] or [])]
        for state in states:
            if len(state) != 2:
                raise CommandError(f"--state takes a two-letter code, got {state!r}")

        plan = build_plan(
            election_ids=options["election_ids"],
            states=states or None,
            delete_results=options["delete_results"],
        )

        if options["apply"]:
            if not plan["elections"]:
                raise CommandError("Nothing to repair for the selected scope")
            plan = apply_plan(plan)

        if options["report"]:
            Path(options["report"]).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")

        self.stdout.write(
            json.dumps(
                {
                    "mode": "applied" if plan["applied"] else "dry_run",
                    "delete_results": plan["delete_results"],
                    **plan["totals"],
                    "deleted_result_rows": plan.get("deleted_result_rows", 0),
                    "affected": [
                        {
                            "election_id": e["election_id"],
                            "state": e["state"],
                            "election_date": e["election_date"],
                            "status": e["status"],
                            "races": len(e["races"]),
                        }
                        for e in plan["elections"]
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
