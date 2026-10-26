"""Refetch NC ENRS directly; preview by default and apply only a reviewed fingerprint."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from elections.models import Election
from integrations.nc_sbe.client import NcSbeClient, _results_zip_url, parse_results_tsv
from results.adapters.base import AdapterResult
from results.adapters.nc import _aggregate_rows
from results.nc_repair import RepairConflict, apply_repair_plan, build_repair_plan


class Command(BaseCommand):
    help = "Preview NC contest identity repair; --apply requires a reviewed, unchanged --approved-report."

    def add_arguments(self, parser):
        parser.add_argument("--election-id", type=int, required=True)
        parser.add_argument(
            "--race-id",
            dest="race_ids",
            type=int,
            action="append",
            default=None,
            help="Limit to this race and its complete connected duplicate/split group; repeatable.",
        )
        parser.add_argument("--report", required=True, help="Write the complete JSON audit report here.")
        parser.add_argument(
            "--source-file", help="Use a saved official ZIP; its SHA256 participates in the review token."
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Preview only (the default).")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--approved-report", help="Prior dry-run JSON; source and database must still match.")

    def handle(self, *args, **options):
        election = Election.objects.filter(pk=options["election_id"], state="NC").first()
        if not election:
            raise CommandError("Select an existing NC election")
        if election.election_date > timezone.localdate():
            raise CommandError("Cannot repair future election results")
        approved = None
        if options["apply"]:
            if not options["approved_report"]:
                raise CommandError("--apply requires --approved-report from a reviewed dry-run")
            if Path(options["approved_report"]).resolve() == Path(options["report"]).resolve():
                raise CommandError("Use a separate output --report to preserve the approved report")
            try:
                approved = json.loads(Path(options["approved_report"]).read_text())
            except (OSError, ValueError) as exc:
                raise CommandError(f"Cannot read approved report: {exc}") from exc
            if (
                approved.get("election_id") != election.pk
                or not approved.get("dry_run")
                or approved.get("applied")
                or not approved.get("fingerprint")
                or approved.get("scope_race_ids") != (sorted(options["race_ids"]) if options["race_ids"] else None)
            ):
                raise CommandError("Approved report must be an unapplied dry-run for the same election and scope")
        day = election.election_date.strftime("%Y_%m_%d")
        source_url = _results_zip_url(day)
        try:
            # Direct download deliberately bypasses adapter ETag/cache. A changed
            # source must invalidate the reviewed plan rather than silently apply.
            content = (
                Path(options["source_file"]).read_bytes()
                if options["source_file"]
                else NcSbeClient().fetch_results_zip(day)
            )
            raw_rows = parse_results_tsv(content)
            for row in raw_rows:
                value = (row.get("Election Date") or "").strip()
                try:
                    source_day = datetime.strptime(value, "%m/%d/%Y").date()
                except ValueError as exc:
                    raise RepairConflict(f"Invalid source election date: {value!r}") from exc
                if source_day != election.election_date:
                    raise RepairConflict(f"Source election date {source_day} differs from selected election")
            result = AdapterResult(
                _aggregate_rows(raw_rows),
                source_url,
                "full",
                source_version=hashlib.sha256(content).hexdigest(),
            )
            report = build_repair_plan(election, result, race_ids=options["race_ids"])
        except (RepairConflict, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        output = Path(options["report"])
        # Write a fresh report even when apply fails, so the reason remains reviewable.
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if approved:
            try:
                with transaction.atomic():
                    report = apply_repair_plan(election, result, approved["fingerprint"], race_ids=options["race_ids"])
                    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            except RepairConflict as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "mode": "applied" if report["applied"] else "dry_run",
                    **report["inventory"],
                    "conflicts": len(report["conflicts"]),
                    "fingerprint": report["fingerprint"],
                    "report": str(output),
                },
                sort_keys=True,
            )
        )
