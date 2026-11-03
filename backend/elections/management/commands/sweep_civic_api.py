"""
Sweep the rows left behind by the retired Google Civic API integration.

WHY THIS EXISTS
---------------
The Civic integration was removed in full (issue #229), but earlier pulls left
rows behind. Civic never key-matched any state adapter -- its nationwide
election is country-scoped, so ``ingest_election`` could not build a canonical
key and ``ingest_race`` fell back to an ``e<pk>|`` prefix -- so most of what it
wrote is a parallel copy of contests a state adapter also holds.

WHAT "ORPHAN" DOES *NOT* MEAN
-----------------------------
``contributing_sources == ["civic_api"]`` is NOT sufficient grounds to delete a
Race. Two independent reasons, both confirmed against production:

1. ``results/tasks.py`` writes ``OfficialResult`` rows WITHOUT routing through
   ``aggregation.ingest``, so it never records itself in ``contributing_sources``
   or ``field_provenance``. MD #1888 races 11003/11004 are ``civic_api`` on every
   single field yet hold certified results from elections.maryland.gov.
   ``OfficialResult.race`` is ``on_delete=CASCADE``, so a naive delete destroys
   those results *silently* -- no error, no warning.
2. For six of the nine affected elections, the Civic races are the ONLY races in
   the election. Deleting them dedupes nothing; it empties the election.

So the sweep holds a race back when EITHER condition is true. Both rules are
structural, evaluated per run -- not a hand-maintained allowlist -- so they stay
correct as the data changes.

WHAT RELEASES THE CONTACT LOCKS
-------------------------------
Deleting the ``civic_api`` ``SourcePrecedence`` rows is what actually unblocks
the fields Civic owns: ``precedence.resolve_rank`` returns ``float("inf")`` for a
source with no rows, and ``ingest._apply_fields`` writes whenever
``incoming <= owner_rank``, so every other source can then overwrite. Clearing
the empty-valued provenance entries is done as well, so the stored provenance
stops claiming Civic owns a field it never filled.

IDEMPOTENCY
-----------
Every step is a no-op on a second run: the deletes are filtered on conditions
the first run cleared, and the provenance/contributing-source edits are applied
only where the Civic entry is still present.

ORDERING
--------
Run this only after the Civic retirement has shipped AND the 04:00
``sync-elections`` crontab entry is gone, or the next sync re-creates what this
removes. Use ``--dry-run`` first; rehearse against a clone before production.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, Race

SOURCE = "civic_api"
_CONTACT_FIELDS = ("image_url", "website_url", "description")


def _held_reasons(race, deletable_election_ids: set[int]) -> list[str]:
    """Why this Civic-only race must be kept. Empty list == safe to delete."""
    reasons = []
    if race.official_results.exists():
        reasons.append("has OfficialResult rows (CASCADE would destroy them)")
    if race.election_id not in deletable_election_ids:
        # "Sole source" only protects a *real* election identity. A keyless
        # election is itself the Civic defect -- ingest_election could not build
        # a canonical key, so the row is an artifact and its contests belong to
        # the per-state elections instead. Holding those would preserve the bug.
        if race.election.canonical_key:
            reasons.append("sole source of races for its election")
    return reasons


class Command(BaseCommand):
    help = "Sweep rows left behind by the retired Google Civic API integration (issue #229)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change and roll back without writing.",
        )
        parser.add_argument(
            "--audit-file", default="",
            help="Write the full per-row audit to this path as JSON.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        audit: dict = {"dry_run": dry_run}

        with transaction.atomic():
            audit["races"] = self._sweep_races()
            audit["merged_races"] = self._strip_merged_races()
            audit["contact_locks"] = self._release_contact_locks()
            audit["precedence"] = self._delete_precedence()
            audit["shells"] = self._report_shells()

            if options["audit_file"]:
                with open(options["audit_file"], "w") as fh:
                    json.dump(audit, fh, indent=2, default=str)
                self.stdout.write(f"audit written to {options['audit_file']}")

            self._print(audit)

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("\nDRY RUN — rolled back, nothing written."))
                return

        self.stdout.write(self.style.SUCCESS("\nSweep applied."))

    # ---- races ---------------------------------------------------------

    def _sweep_races(self) -> dict:
        civic_only = Q(contributing_sources=[SOURCE])

        # An election is safe to delete Civic races from only if something else
        # would remain afterwards.
        #
        # Counted by grouping Race rows, NOT by annotating Election. Two traps
        # live on that path: Election has its own `contributing_sources` field,
        # so a bare Q() resolves against the wrong model; and filtering a
        # reverse relation then counting it counts only the joined rows, so
        # total == civic_count and every election looks like a sole-source one.
        per_election = (
            Race.objects.values("election_id")
            .annotate(total=Count("pk"), civic=Count("pk", filter=civic_only))
        )
        deletable_election_ids = {
            row["election_id"] for row in per_election if row["total"] > row["civic"]
        }

        deleted, held = [], []
        for race in Race.objects.filter(civic_only).select_related("election"):
            reasons = _held_reasons(race, deletable_election_ids)
            row = {
                "race": race.pk,
                "office": race.office_title[:60],
                "election": race.election_id,
                "state": race.election.state or None,
                "candidates": race.candidates.count(),
                "measure_options": race.measure_options.count(),
            }
            if reasons:
                row["reasons"] = reasons
                held.append(row)
                continue
            # Report what CASCADE will take with the race.
            #
            # Non-Civic contributing_sources (e.g. openstates) re-attach on that
            # source's next sync, so those are recoverable. Contact values that
            # Civic itself supplied are NOT -- Civic is retired and cannot
            # re-supply them -- so the actual values are recorded here, in the
            # audit file, before the row goes.
            enriched = list(
                race.candidates.exclude(contributing_sources=[SOURCE])
                .exclude(contributing_sources=[])
                .values_list("name", "contributing_sources")
            )
            if enriched:
                row["candidate_enrichment_lost"] = [
                    {"name": n, "sources": s} for n, s in enriched
                ]
            civic_contacts = []
            for cand in race.candidates.all():
                prov = cand.field_provenance or {}
                civic_owned = {
                    f: getattr(cand, f, "")
                    for f in _CONTACT_FIELDS
                    if prov.get(f) == SOURCE and getattr(cand, f, "")
                }
                if civic_owned:
                    civic_contacts.append({"name": cand.name, **civic_owned})
            if civic_contacts:
                row["civic_contact_values_lost"] = civic_contacts
            deleted.append(row)

        Race.objects.filter(pk__in=[r["race"] for r in deleted]).delete()
        return {"deleted": deleted, "held": held}

    def _strip_merged_races(self) -> list[dict]:
        """Civic contributed alongside a state adapter: keep the row, drop Civic."""
        rows = []
        qs = Race.objects.filter(contributing_sources__contains=[SOURCE]).exclude(
            contributing_sources=[SOURCE]
        )
        for race in qs:
            sources = [s for s in (race.contributing_sources or []) if s != SOURCE]
            prov = dict(race.field_provenance or {})
            reassigned = [k for k, v in prov.items() if v == SOURCE]
            fallback = sources[0] if sources else None
            for key in reassigned:
                if fallback:
                    prov[key] = fallback
                else:
                    prov.pop(key)
            rows.append({
                "race": race.pk,
                "office": race.office_title[:60],
                "remaining_sources": sources,
                "provenance_reassigned_to": fallback,
                "fields": reassigned,
            })
            race.contributing_sources = sources
            race.field_provenance = prov
            race.save(update_fields=["contributing_sources", "field_provenance"])
        return rows

    # ---- contact locks -------------------------------------------------

    def _release_contact_locks(self) -> dict:
        """Drop provenance entries where Civic owns an EMPTY contact field.

        Entries holding a real value are left alone -- that data is genuine and
        stays attributed to its source.
        """
        released = 0
        preserved = 0
        owned = Q()
        for field in _CONTACT_FIELDS:
            owned |= Q(**{f"field_provenance__{field}": SOURCE})
        candidates = Candidate.objects.filter(owned)
        for cand in candidates.iterator():
            prov = dict(cand.field_provenance or {})
            changed = False
            for field in _CONTACT_FIELDS:
                if prov.get(field) != SOURCE:
                    continue
                if getattr(cand, field, "") == "":
                    prov.pop(field)
                    changed = True
                else:
                    preserved += 1
            if changed:
                cand.field_provenance = prov
                cand.save(update_fields=["field_provenance"])
                released += 1
        return {"candidates_released": released, "real_values_preserved": preserved}

    # ---- precedence ----------------------------------------------------

    def _delete_precedence(self) -> dict:
        qs = SourcePrecedence.objects.filter(source=SOURCE)
        rows = list(qs.values("state", "field_group", "rank"))
        wildcard = any(r["state"] == "*" and r["field_group"] == "*" for r in rows)
        qs.delete()
        return {"deleted": len(rows), "included_global_wildcard": wildcard}

    # ---- shells --------------------------------------------------------

    def _report_shells(self) -> list[dict]:
        """Keyless Election rows. Reported only -- never mutated.

        ``state`` is left NULL deliberately: both results pollers filter
        ``state__in=supported``, so a NULL state is what keeps these rows
        permanently poller-ineligible. Backfilling a state would make them
        eligible again.
        """
        return [
            {
                "election": e.pk,
                "name": e.name[:60],
                "state": e.state or None,
                "races_remaining": e.races.count(),
                "needs_review": e.needs_review,
            }
            for e in Election.objects.filter(canonical_key__isnull=True).order_by("pk")
        ]

    # ---- reporting -----------------------------------------------------

    def _print(self, audit: dict) -> None:
        races = audit["races"]
        out = self.stdout.write
        out("")
        out(f"races deleted                 : {len(races['deleted'])}")
        out(f"races HELD (kept on purpose)  : {len(races['held'])}")
        for row in races["held"]:
            out(f"    race {row['race']} (election {row['election']}, {row['state']}): "
                f"{row['office']} — {'; '.join(row['reasons'])}")
        lost = [r for r in races["deleted"] if r.get("candidate_enrichment_lost")]
        if lost:
            out(f"  deleted races carrying non-Civic candidate enrichment: {len(lost)}"
                f"  (recoverable — that source re-syncs)")
            for row in lost:
                for c in row["candidate_enrichment_lost"]:
                    out(f"    {c['name']} ({', '.join(c['sources'])}) on race {row['race']}")
        contacts = [r for r in races["deleted"] if r.get("civic_contact_values_lost")]
        if contacts:
            n = sum(len(r["civic_contact_values_lost"]) for r in contacts)
            out(self.style.WARNING(
                f"  PERMANENT: {n} candidate contact value(s) supplied by Civic will be lost"
                f" (Civic is retired and cannot re-supply them; values are in the audit file)"))
            for row in contacts:
                for c in row["civic_contact_values_lost"]:
                    fields = ", ".join(f"{k}={v[:46]}" for k, v in c.items() if k != "name")
                    out(f"    {c['name']} on race {row['race']}: {fields}")
        out(f"merged races stripped of Civic: {len(audit['merged_races'])}")
        cl = audit["contact_locks"]
        out(f"contact locks released        : {cl['candidates_released']} candidates")
        out(f"  real Civic values preserved : {cl['real_values_preserved']} fields")
        pr = audit["precedence"]
        out(f"SourcePrecedence rows deleted : {pr['deleted']}"
            f" (global wildcard: {pr['included_global_wildcard']})")
        out(f"keyless election shells       : {len(audit['shells'])} (reported, not modified)")
        for row in audit["shells"]:
            out(f"    election {row['election']}: {row['name']} "
                f"[state={row['state']}, races={row['races_remaining']}]")
