import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from cm2_elections.admin import ContestAdmin, ElectionAdmin
from cm2_elections.models import Contest, Election, LifecycleAuditEvent


def _admin_request(rf, user, post_data=None):
    request = rf.post("/admin/cm2_elections/election/", data=post_data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.fixture
def election_admin():
    return ElectionAdmin(Election, AdminSite())


@pytest.fixture
def contest_admin():
    return ContestAdmin(Contest, AdminSite())


@pytest.mark.django_db
def test_save_model_records_status_change_on_election(election, election_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-1")
    rf = RequestFactory()
    request = _admin_request(rf, actor)

    election.lifecycle_status = Election.LifecycleStatus.CANCELLED
    form = type("Form", (), {"changed_data": ["lifecycle_status"]})()

    election_admin.save_model(request, election, form, change=True)

    event = election.lifecycle_audit_events.get(event_type=LifecycleAuditEvent.EventType.STATUS_CHANGED)
    assert event.actor == actor
    assert event.metadata == {"old_status": "upcoming", "new_status": "cancelled"}


@pytest.mark.django_db
def test_save_model_skips_audit_when_status_unchanged(election, election_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-2")
    rf = RequestFactory()
    request = _admin_request(rf, actor)
    form = type("Form", (), {"changed_data": ["name"]})()

    election_admin.save_model(request, election, form, change=True)

    assert not election.lifecycle_audit_events.exists()


@pytest.mark.django_db
def test_save_model_skips_audit_on_create(election_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-3")
    rf = RequestFactory()
    request = _admin_request(rf, actor)
    new_election = Election(
        name="2027 Special Election",
        election_date="2027-01-05",
        election_type=Election.ElectionType.SPECIAL,
    )
    form = type("Form", (), {"changed_data": ["name", "election_date", "election_type"]})()

    election_admin.save_model(request, new_election, form, change=False)

    assert not LifecycleAuditEvent.objects.filter(election=new_election).exists()


@pytest.mark.django_db
def test_add_lifecycle_note_action_requires_note_text(election, election_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-4")
    rf = RequestFactory()
    request = _admin_request(rf, actor, post_data={})

    election_admin.add_lifecycle_note(request, Election.objects.filter(pk=election.pk))

    assert not election.lifecycle_audit_events.exists()


@pytest.mark.django_db
def test_add_lifecycle_note_action_creates_event_for_each_selected(election, election_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-5")
    rf = RequestFactory()
    request = _admin_request(rf, actor, post_data={"note": "NCSBE voided this race; re-vote ordered."})

    election_admin.add_lifecycle_note(request, Election.objects.filter(pk=election.pk))

    event = election.lifecycle_audit_events.get(event_type=LifecycleAuditEvent.EventType.NOTE_ADDED)
    assert event.actor == actor
    assert "NCSBE voided" in event.note


@pytest.mark.django_db
def test_save_model_records_status_change_on_contest(contest, contest_admin, django_user_model):
    actor = django_user_model.objects.create_user(username="lifecycle-admin-6")
    rf = RequestFactory()
    request = _admin_request(rf, actor)
    contest.lifecycle_status = Contest.LifecycleStatus.CANCELLED
    form = type("Form", (), {"changed_data": ["lifecycle_status"]})()

    contest_admin.save_model(request, contest, form, change=True)

    event = contest.lifecycle_audit_events.get(event_type=LifecycleAuditEvent.EventType.STATUS_CHANGED)
    assert event.metadata == {"old_status": "upcoming", "new_status": "cancelled"}
