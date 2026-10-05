from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Contest, Election, LifecycleAuditEvent


def record_lifecycle_event(
    entity: Election | Contest,
    event_type: str,
    actor,
    *,
    note: str = "",
    metadata: dict | None = None,
) -> LifecycleAuditEvent:
    """Record an immutable audit event against an Election or Contest."""
    if isinstance(entity, Election):
        target = {"election": entity}
    elif isinstance(entity, Contest):
        target = {"contest": entity}
    else:
        raise ValidationError({"entity": "Lifecycle events may only target an Election or Contest."})

    return LifecycleAuditEvent.objects.create(
        actor=actor,
        event_type=event_type,
        note=note,
        metadata=metadata or {},
        **target,
    )


@transaction.atomic
def record_lifecycle_note(entity: Election | Contest, *, actor, note: str) -> LifecycleAuditEvent:
    """Attach a freestanding reviewer note to an Election or Contest, independent of a status change."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise ValidationError("An authenticated actor is required.")
    if not note.strip():
        raise ValidationError({"note": "A note is required."})

    return record_lifecycle_event(entity, LifecycleAuditEvent.EventType.NOTE_ADDED, actor, note=note)
