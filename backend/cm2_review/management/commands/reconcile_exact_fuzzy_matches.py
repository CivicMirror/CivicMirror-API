"""
Auto-resolve open ``fuzzy_person_match`` review cases that have exactly one
candidate, a perfect (1.0) name-similarity score, no conflicting evidence, and
no structured-field disagreement — the "everything matches" bucket a reviewer
would otherwise merge by hand one at a time.

WHY THIS EXISTS
---------------
A large ingestion run can create hundreds of fuzzy-match cases where the
matcher already found an exact name match against an existing Person; the only
thing making them "fuzzy" instead of a deterministic link is that the matching
signal was a name string rather than a stable identifier. Reviewing each of
these by hand is pure toil with no judgment call involved, so this command
applies the exact same resolution (Merge people, via ``transition_review_case``)
that a reviewer would apply by clicking "Merge people into <name>" on every
qualifying case.

SELECTION CRITERIA (all must hold)
-----------------------------------
- case_type == fuzzy_person_match, status == open
- exactly one IdentityReviewSuggestion
- suggestion.score == 1.0 exactly (not merely high)
- suggestion.conflicting_evidence is empty
- given/middle/family/suffix name parts that are non-blank on both the source
  record and the suggested person match case-insensitively (never a silent
  override — a genuine mismatch anywhere disqualifies the case)
- the case has a provisional_person, and it isn't the same row as the
  suggested person
- the suggested person's identity_state isn't already merged or disputed

Anything that doesn't meet every criterion is left untouched for a human.

DEPLOYMENT NOTE
----------------
Idempotent: a second run only ever sees cases already resolved out of the
`open` queryset, so it is always safe to re-run after a new ingestion batch.
"""

import json
import logging
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cm2_elections.models import Person
from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import transition_review_case

logger = logging.getLogger(__name__)


def _norm(value):
    return (value or "").strip().lower()


def _name_fields_agree(source, person):
    """True unless a non-blank field disagrees on both sides. Blank-vs-present
    is not a disagreement (the matcher already scored the record 1.0 on the
    full name string); only a genuine two-sided mismatch disqualifies it."""
    for source_attr, person_attr in (
        ("given_name", "given_name"),
        ("middle_name", "middle_name"),
        ("family_name", "family_name"),
        ("suffix", "suffix"),
    ):
        a = _norm(getattr(source, source_attr, ""))
        b = _norm(getattr(person, person_attr, ""))
        if a and b and a != b:
            return False
    return True


def _qualifies(case):
    """Return (suggestion, None) if eligible, or (None, skip_reason) otherwise."""
    suggestions = list(case.suggestions.all())
    if len(suggestions) != 1:
        return None, "multiple_or_no_suggestions"
    suggestion = suggestions[0]
    if suggestion.score is None or float(suggestion.score) != 1.0:
        return None, "score_not_exact"
    if suggestion.conflicting_evidence:
        return None, "has_conflicting_evidence"
    person = suggestion.suggested_person
    if person is None:
        return None, "no_suggested_person"
    if case.provisional_person_id is None:
        return None, "no_provisional_person"
    if case.provisional_person_id == person.id:
        return None, "self_target"
    if person.identity_state in {Person.IdentityState.MERGED, Person.IdentityState.DISPUTED}:
        return None, "target_not_resolvable"
    source = case.source_record
    if source is None:
        return None, "no_source_record"
    if not _name_fields_agree(source, person):
        return None, "structured_name_field_mismatch"
    return suggestion, None


class Command(BaseCommand):
    help = (
        "Auto-resolve open fuzzy_person_match cases with a single, exact "
        "(score 1.0), conflict-free candidate via the Merge people action."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview actions without writing any changes.",
        )
        parser.add_argument(
            "--reviewer", type=str, required=True,
            help="Username to record as reviewer on every resolved case.",
        )
        parser.add_argument(
            "--audit-file", type=str, default=None,
            help="Path for the JSONL audit log (default: timestamped in cwd).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apply_changes = not dry_run

        User = get_user_model()
        try:
            reviewer = User.objects.get(username=options["reviewer"])
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with username {options['reviewer']!r}.") from exc

        cases = (
            IdentityReviewCase.objects.filter(
                case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
                status=IdentityReviewCase.Status.OPEN,
            )
            .select_related("source_record", "provisional_person")
            .prefetch_related("suggestions__suggested_person")
        )

        suffix = ".dryrun.jsonl" if dry_run else ".jsonl"
        audit_path = options["audit_file"] or (
            f"reconcile_exact_fuzzy_matches_{datetime.now(UTC):%Y%m%dT%H%M%SZ}{suffix}"
        )
        audit_fh = open(audit_path, "w", encoding="utf-8")

        def audit(record):
            line = json.dumps(record, default=str)
            audit_fh.write(line + "\n")
            logger.info("reconcile_exact_fuzzy_matches.audit %s", line)

        mode = "DRY RUN" if dry_run else "APPLY"
        total = cases.count()
        self.stdout.write(f"[{mode}] scanning {total} open fuzzy_person_match case(s)...")

        resolved = 0
        skipped = {}
        errors = 0

        try:
            for case in cases.iterator(chunk_size=200):
                suggestion, skip_reason = _qualifies(case)
                if skip_reason is not None:
                    skipped[skip_reason] = skipped.get(skip_reason, 0) + 1
                    continue

                record = {
                    "case_id": str(case.public_id),
                    "provisional_person_id": case.provisional_person_id,
                    "provisional_person_name": case.provisional_person.canonical_name,
                    "target_person_id": suggestion.suggested_person_id,
                    "target_person_name": suggestion.suggested_person.canonical_name,
                    "score": str(suggestion.score),
                }

                if not apply_changes:
                    audit(record)
                    resolved += 1
                    continue

                try:
                    with transaction.atomic():
                        transition_review_case(
                            case,
                            reviewer=reviewer,
                            status=IdentityReviewCase.Status.APPROVED,
                            action=IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
                            target_person=suggestion.suggested_person,
                        )
                except ValidationError as exc:
                    errors += 1
                    record["error"] = "; ".join(exc.messages)
                    audit(record)
                    logger.error(
                        "reconcile_exact_fuzzy_matches: case %s failed: %s",
                        case.public_id, record["error"],
                    )
                    continue

                audit(record)
                resolved += 1
        finally:
            audit_fh.close()

        self.stdout.write(self.style.SUCCESS(f"[{mode}] done."))
        self.stdout.write(f"  scanned   : {total}")
        self.stdout.write(f"  resolved  : {resolved}")
        self.stdout.write(f"  errors    : {errors}")
        for reason, count in sorted(skipped.items()):
            self.stdout.write(f"  skipped ({reason}): {count}")
        self.stdout.write(f"  audit log: {audit_path}")
