"""Preview by default; apply a reviewed, freshly verified classification report."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from elections.models import Election
from integrations.nc_sbe.client import NcSbeClient, _results_zip_url, parse_candidate_listing_csv, parse_results_tsv
from integrations.nc_sbe.election_repair import (
    ClassificationConflict,
    apply_classification_plan,
    build_classification_plan,
)
from integrations.nc_sbe.exceptions import NcSbeRetryableError
from results.adapters.nc import _aggregate_rows


class Command(BaseCommand):
    help = "Preview NC jurisdiction/phase classification; apply requires an unchanged approved report."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--election-id", type=int)
        scope.add_argument("--all-nc", action="store_true")
        parser.add_argument("--report", required=True)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--approved-report")
        parser.add_argument("--source-file", help="Saved official results ZIP (single Election only).")
        parser.add_argument("--filing-file", help="Saved official annual filing CSV (single Election only).")

    def handle(self, *args, **options):
        output = Path(options["report"])
        if options["all_nc"] and (options["source_file"] or options["filing_file"]):
            raise CommandError("Saved files require a single --election-id")
        approved = None
        if options["apply"]:
            if not options["approved_report"]:
                raise CommandError("--apply requires --approved-report")
            if output.resolve() == Path(options["approved_report"]).resolve():
                raise CommandError("Preserve the approved report; use a separate output path")
            try:
                approved = json.loads(Path(options["approved_report"]).read_text())
            except (OSError, ValueError) as exc:
                raise CommandError(f"Cannot read approved report: {exc}") from exc
        elections = Election.objects.filter(state="NC").order_by("election_date", "pk")
        if options["election_id"]:
            elections = elections.filter(pk=options["election_id"])
        else:
            elections = elections.exclude(source_metadata__has_key="nc_classification_parent_id")
        elections = list(elections)
        if not elections:
            raise CommandError("Select an existing NC election")
        if approved and options["all_nc"]:
            if not approved.get("dry_run") or approved.get("applied") or "elections" not in approved:
                raise CommandError("Approved report must be an unapplied all-NC preview")
            expected_ids = [item["election_id"] for item in approved["elections"]]
            if expected_ids != [e.pk for e in elections]:
                raise CommandError("NC election scope changed; review a fresh preview")
        client = NcSbeClient()

        def fetch(method, *args):
            for attempt in range(3):
                try:
                    return method(*args)
                except NcSbeRetryableError as exc:
                    cause = exc.__cause__
                    if (isinstance(cause, requests.HTTPError) and cause.response.status_code == 404) or attempt == 2:
                        raise
                    time.sleep(attempt + 1)

        annual = {}
        reports = []

        def save():
            payload = (
                {
                    "dry_run": not options["apply"],
                    "applied": len(reports) == len(elections) and all(r["applied"] for r in reports),
                    "scope_election_ids": [e.pk for e in elections],
                    "completed_election_ids": [r["election_id"] for r in reports if r["applied"]],
                    "elections": reports,
                }
                if options["all_nc"]
                else reports[-1]
            )
            output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

        for election in elections:
            try:
                year = election.election_date.year
                if year not in annual:
                    key = fetch(client.list_candidate_filing_csv_key, str(year)) if not options["filing_file"] else None
                    content = (
                        Path(options["filing_file"]).read_bytes()
                        if options["filing_file"]
                        else fetch(client.fetch_candidate_filing_csv, key)
                        if key
                        else b""
                    )
                    annual[year] = (content, parse_candidate_listing_csv(content))
                filing_bytes, filing_rows = annual[year]
                source_state = "downloaded"
                try:
                    result_bytes = (
                        Path(options["source_file"]).read_bytes()
                        if options["source_file"]
                        else fetch(client.fetch_results_zip, election.election_date.strftime("%Y_%m_%d"))
                    )
                except NcSbeRetryableError as exc:
                    cause = exc.__cause__
                    if isinstance(cause, requests.HTTPError) and cause.response.status_code == 404:
                        result_bytes, source_state = b"", "http_404"
                    else:
                        raise
                raw_rows = parse_results_tsv(result_bytes) if result_bytes else []
                for row in raw_rows:
                    value = (row.get("Election Date") or "").strip()
                    if value and datetime.strptime(value, "%m/%d/%Y").date() != election.election_date:
                        raise ClassificationConflict("Source election date differs from selected election")
                result_rows = _aggregate_rows(raw_rows)
                hashes = {
                    "filings": hashlib.sha256(filing_bytes).hexdigest(),
                    "results": hashlib.sha256(result_bytes).hexdigest(),
                    "results_state": source_state,
                    "results_url": _results_zip_url(election.election_date.strftime("%Y_%m_%d")),
                }
                report = build_classification_plan(election, filing_rows, result_rows, hashes)
                reports.append(report)
                if approved:
                    token = (
                        next(item for item in approved["elections"] if item["election_id"] == election.pk)
                        if options["all_nc"]
                        else approved
                    )

                    def write_applied(value):
                        reports[-1] = value
                        save()

                    apply_classification_plan(
                        election, filing_rows, result_rows, hashes, token, write_report=write_applied
                    )
                else:
                    save()
                self.stdout.write(
                    json.dumps(
                        {
                            "election_id": election.pk,
                            "applied": bool(approved),
                            **report["counts"],
                            "targets": len(report["targets"]),
                            "fingerprint": report["fingerprint"],
                        }
                    )
                )
            except (ClassificationConflict, NcSbeRetryableError, OSError, ValueError, requests.RequestException) as exc:
                raise CommandError(str(exc)) from exc
