from __future__ import annotations

from django.db import transaction

from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase
from cm2_review.workflow import create_review_case


def flag_incomplete_election(*, deduplication_key: str, supporting_evidence: dict) -> tuple[IdentityReviewCase, bool]:
    """
    Record (or refresh) a review case for a discovered candidate/office whose
    election date isn't known yet, so it's tracked for human resolution and
    picked up on a later ingestion run instead of being silently dropped
    (ElectionRecord.election_date has no null/placeholder path).

    Idempotent on `deduplication_key`: a repeat call while the case is still
    OPEN refreshes `supporting_evidence` in place rather than creating a
    duplicate row. A repeat call after the case has been resolved (or
    deferred/rejected) leaves it untouched -- callers should check
    get_resolved_incomplete_election() for a resolved case before calling
    this again for the same discovery.
    """
    review_case, created = create_review_case(
        defaults={
            "case_type": IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
            "supporting_evidence": supporting_evidence,
        },
        deduplication_key=deduplication_key,
    )
    if not created and review_case.status == IdentityReviewCase.Status.OPEN:
        review_case.supporting_evidence = supporting_evidence
        review_case.save(update_fields=["supporting_evidence", "updated_at"])
    return review_case, created


def get_resolved_incomplete_election(deduplication_key: str) -> IdentityReviewCase | None:
    """
    Look up an approved incomplete-election-data case ready for promotion
    into a real Election/Contest/Candidacy. Returns None if no case exists
    for this key, or it exists but hasn't been approved with
    SUPPLY_MISSING_DATA yet (still open, deferred, or rejected).
    """
    return IdentityReviewCase.objects.filter(
        deduplication_key=deduplication_key,
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        status=IdentityReviewCase.Status.APPROVED,
        resolution_action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
    ).first()


@transaction.atomic
def defer_failed_promotion(review_case: IdentityReviewCase, *, error: str) -> IdentityReviewCase:
    """
    Move a case back to DEFERRED after an ingestion run tried to promote its
    supplied resolution_data and hit a downstream validation error (e.g. the
    rebuilt batch still failed validate_pre_election_batch for an unrelated
    reason). Distinct from transition_review_case: this is a system-triggered
    transition, not a new human decision, so it bypasses the
    authenticated-reviewer gate and records the error on conflicting_evidence
    rather than notes, alongside the original supporting_evidence.
    """
    review_case.status = IdentityReviewCase.Status.DEFERRED
    review_case.conflicting_evidence = {
        **(review_case.conflicting_evidence or {}),
        "promotion_error": error,
    }
    review_case.save(update_fields=["status", "conflicting_evidence", "updated_at"])
    IdentityReviewAuditEvent.objects.create(
        review_case=review_case,
        actor=None,
        event_type=IdentityReviewAuditEvent.EventType.DEFERRED,
        metadata={"reason": "promotion_failed", "error": error},
        has_private_evidence=review_case.has_private_evidence,
    )
    return review_case
