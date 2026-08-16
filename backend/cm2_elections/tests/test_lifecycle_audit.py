import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cm2_elections.models import LifecycleAuditEvent
from cm2_elections.workflow import record_lifecycle_event, record_lifecycle_note


@pytest.mark.django_db
def test_lifecycle_event_requires_exactly_one_subject(election, contest):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            LifecycleAuditEvent.objects.create(event_type=LifecycleAuditEvent.EventType.NOTE_ADDED)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            LifecycleAuditEvent.objects.create(
                election=election,
                contest=contest,
                event_type=LifecycleAuditEvent.EventType.NOTE_ADDED,
            )


@pytest.mark.django_db
def test_lifecycle_audit_events_are_immutable(election):
    event = LifecycleAuditEvent.objects.create(
        election=election,
        event_type=LifecycleAuditEvent.EventType.NOTE_ADDED,
        note="Initial note.",
    )

    event.note = "Changed after the fact."
    with pytest.raises(ValidationError, match="immutable"):
        event.save()


@pytest.mark.django_db
def test_record_lifecycle_event_rejects_unsupported_entity(django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-actor")
    with pytest.raises(ValidationError, match="entity"):
        record_lifecycle_event(object(), LifecycleAuditEvent.EventType.NOTE_ADDED, actor)


@pytest.mark.django_db
def test_record_lifecycle_event_targets_election_or_contest(election, contest, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-actor-2")

    election_event = record_lifecycle_event(
        election,
        LifecycleAuditEvent.EventType.STATUS_CHANGED,
        actor,
        metadata={"old_status": "upcoming", "new_status": "cancelled"},
    )
    contest_event = record_lifecycle_event(contest, LifecycleAuditEvent.EventType.STATUS_CHANGED, actor)

    assert election_event.election_id == election.id
    assert election_event.contest_id is None
    assert election_event.metadata == {"old_status": "upcoming", "new_status": "cancelled"}
    assert contest_event.contest_id == contest.id
    assert contest_event.election_id is None


@pytest.mark.django_db
def test_record_lifecycle_note_requires_authenticated_actor(election):
    with pytest.raises(ValidationError, match="actor"):
        record_lifecycle_note(election, actor=None, note="News report of a re-vote order.")

    assert not election.lifecycle_audit_events.exists()


@pytest.mark.django_db
def test_record_lifecycle_note_requires_nonempty_note(election, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-note-actor")
    with pytest.raises(ValidationError, match="note"):
        record_lifecycle_note(election, actor=actor, note="   ")


@pytest.mark.django_db
def test_record_lifecycle_note_creates_note_added_event(election, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-note-actor-2")

    event = record_lifecycle_note(
        election,
        actor=actor,
        note="NCSBE voided this election; town must re-run in March.",
    )

    assert event.event_type == LifecycleAuditEvent.EventType.NOTE_ADDED
    assert event.actor == actor
    assert "NCSBE voided" in event.note
    assert election.lifecycle_audit_events.count() == 1
