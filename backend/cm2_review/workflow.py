from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cm2_elections.models import Person, PersonIdentifier

from .models import IdentityReviewAuditEvent, IdentityReviewCase, IdentityReviewSuggestion

_TERMINAL_STATUSES = {
    IdentityReviewCase.Status.APPROVED,
    IdentityReviewCase.Status.REJECTED,
}


def _audit(
    review_case: IdentityReviewCase,
    event_type: str,
    actor,
    *,
    metadata: dict | None = None,
) -> IdentityReviewAuditEvent:
    return IdentityReviewAuditEvent.objects.create(
        review_case=review_case,
        actor=actor,
        event_type=event_type,
        metadata=metadata or {},
        has_private_evidence=review_case.has_private_evidence,
    )


@transaction.atomic
def create_review_case(*, defaults: dict, deduplication_key: str) -> tuple[IdentityReviewCase, bool]:
    """Create a review case once and emit its creation event."""
    review_case, created = IdentityReviewCase.objects.get_or_create(
        deduplication_key=deduplication_key,
        defaults=defaults,
    )
    if created:
        _audit(review_case, IdentityReviewAuditEvent.EventType.CREATED, None, metadata={"status": review_case.status})
    return review_case, created


@transaction.atomic
def transition_review_case(
    review_case: IdentityReviewCase,
    *,
    reviewer,
    status: str,
    action: str,
    target_person: Person | None = None,
    target_suggestion: "IdentityReviewSuggestion | None" = None,
    notes: str = "",
) -> IdentityReviewCase:
    """Apply an explicit human review decision and record an audit event."""
    if reviewer is None or not getattr(reviewer, "is_authenticated", False):
        raise ValidationError("An authenticated reviewer is required.")
    if status not in IdentityReviewCase.Status.values:
        raise ValidationError({"status": "Unknown review status."})
    if action not in IdentityReviewCase.ResolutionAction.values:
        raise ValidationError({"action": "Unknown resolution action."})
    if status == IdentityReviewCase.Status.APPROVED and action == IdentityReviewCase.ResolutionAction.DEFER:
        raise ValidationError({"action": "Deferred cases cannot be approved."})
    if status == IdentityReviewCase.Status.DEFERRED and action != IdentityReviewCase.ResolutionAction.DEFER:
        raise ValidationError({"action": "Deferred cases must use the defer action."})
    if status in _TERMINAL_STATUSES and action == IdentityReviewCase.ResolutionAction.DEFER:
        raise ValidationError({"action": "Terminal cases cannot use the defer action."})
    if status == IdentityReviewCase.Status.REJECTED and action != IdentityReviewCase.ResolutionAction.REJECT:
        raise ValidationError({"action": "Rejected cases must use the reject action."})
    if status != IdentityReviewCase.Status.REJECTED and action == IdentityReviewCase.ResolutionAction.REJECT:
        raise ValidationError({"action": "The reject action requires rejected status."})

    if action in {
        IdentityReviewCase.ResolutionAction.LINK_EXISTING,
        IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
    } and target_person is None:
        raise ValidationError({"target_person": "This action requires a target person."})
    if target_person is not None and review_case.provisional_person_id == target_person.id:
        raise ValidationError({"target_person": "A person cannot target itself."})

    if action == IdentityReviewCase.ResolutionAction.LINK_CIVIC_DATA:
        if target_suggestion is None:
            raise ValidationError({"target_suggestion": "This action requires a target suggestion."})
        if target_suggestion.review_case_id != review_case.id:
            raise ValidationError({"target_suggestion": "The suggestion does not belong to this review case."})
        if not target_suggestion.external_scheme or not target_suggestion.external_identifier:
            raise ValidationError({"target_suggestion": "The suggestion has no external identifier to link."})

    review_case = IdentityReviewCase.objects.select_for_update().get(pk=review_case.pk)
    previous_status = review_case.status
    provisional = review_case.provisional_person

    if action == IdentityReviewCase.ResolutionAction.CONFIRM_NEW and provisional is not None:
        provisional.identity_state = Person.IdentityState.RESOLVED
        provisional.merged_into = None
        provisional.save(update_fields=["identity_state", "merged_into", "updated_at"])
    elif action in {
        IdentityReviewCase.ResolutionAction.LINK_EXISTING,
        IdentityReviewCase.ResolutionAction.MERGE_PEOPLE,
    }:
        if provisional is not None:
            provisional.identity_state = Person.IdentityState.MERGED
            provisional.merged_into = target_person
            provisional.save(update_fields=["identity_state", "merged_into", "updated_at"])
        if review_case.source_record_id:
            review_case.source_record.person = target_person
            review_case.source_record.save(update_fields=["person"])
    elif action == IdentityReviewCase.ResolutionAction.REJECT:
        if provisional is not None:
            provisional.identity_state = Person.IdentityState.DISPUTED
            provisional.save(update_fields=["identity_state", "updated_at"])
    elif action == IdentityReviewCase.ResolutionAction.LINK_CIVIC_DATA:
        if provisional is None:
            raise ValidationError({"provisional_person": "This action requires a provisional person."})
        PersonIdentifier.objects.update_or_create(
            scheme=target_suggestion.external_scheme,
            identifier=target_suggestion.external_identifier,
            defaults={
                "person": provisional,
                "verification_method": PersonIdentifier.VerificationMethod.HUMAN_REVIEW,
                "verified_by": reviewer,
                "verified_at": timezone.now(),
            },
        )
        provisional.identity_state = Person.IdentityState.RESOLVED
        provisional.merged_into = None
        provisional.save(update_fields=["identity_state", "merged_into", "updated_at"])

    review_case.status = status
    review_case.resolution_action = action
    review_case.reviewed_by = reviewer
    review_case.reviewed_at = timezone.now()
    if notes:
        review_case.notes = notes
    review_case.save(
        update_fields=[
            "status",
            "resolution_action",
            "reviewed_by",
            "reviewed_at",
            "notes",
            "updated_at",
        ]
    )

    event_type = (
        IdentityReviewAuditEvent.EventType.DEFERRED
        if status == IdentityReviewCase.Status.DEFERRED
        else IdentityReviewAuditEvent.EventType.RESOLVED
    )
    _audit(
        review_case,
        event_type,
        reviewer,
        metadata={"from_status": previous_status, "to_status": status, "action": action},
    )
    return review_case


@transaction.atomic
def supersede_review_case(
    review_case: IdentityReviewCase,
    *,
    superseded_by: IdentityReviewCase,
    actor,
) -> IdentityReviewCase:
    """Mark a review case as replaced by a newer case for the same subject."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise ValidationError("An authenticated actor is required.")
    if superseded_by.pk == review_case.pk:
        raise ValidationError({"superseded_by": "A case cannot supersede itself."})
    if review_case.status in _TERMINAL_STATUSES or review_case.status == IdentityReviewCase.Status.SUPERSEDED:
        raise ValidationError({"status": "Only open or deferred cases can be superseded."})

    review_case = IdentityReviewCase.objects.select_for_update().get(pk=review_case.pk)
    previous_status = review_case.status
    review_case.status = IdentityReviewCase.Status.SUPERSEDED
    review_case.superseded_by = superseded_by
    review_case.save(update_fields=["status", "superseded_by", "updated_at"])

    _audit(
        review_case,
        IdentityReviewAuditEvent.EventType.SUPERSEDED,
        actor,
        metadata={"from_status": previous_status, "superseded_by": str(superseded_by.public_id)},
    )
    return review_case
