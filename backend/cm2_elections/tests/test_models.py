from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cm2_elections.models import (
    Candidacy,
    Contest,
    Jurisdiction,
    Office,
    OfficeTerm,
    Person,
    PersonIdentifier,
    PersonSourceRecord,
)


@pytest.mark.django_db
def test_names_never_merge_people(source_artifact):
    first = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)
    second = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)

    assert first.id != second.id
    assert first.public_id != second.public_id


@pytest.mark.django_db
def test_merged_person_requires_a_different_redirect_target(source_artifact):
    target = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Person.objects.create(
                canonical_name="DeDreana Freeman",
                identity_state=Person.IdentityState.MERGED,
                source_artifact=source_artifact,
            )

    duplicate = Person.objects.create(canonical_name="DeDreana Freeman", source_artifact=source_artifact)
    duplicate.identity_state = Person.IdentityState.MERGED
    duplicate.merged_into = duplicate
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            duplicate.save()

    duplicate.merged_into = target
    duplicate.save()
    assert duplicate.merged_into == target


@pytest.mark.django_db
def test_non_merged_person_cannot_have_redirect_target(source_artifact):
    target = Person.objects.create(canonical_name="Resolved Person", source_artifact=source_artifact)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Person.objects.create(
                canonical_name="Provisional Person",
                identity_state=Person.IdentityState.PROVISIONAL,
                merged_into=target,
                source_artifact=source_artifact,
            )


@pytest.mark.django_db
def test_person_identifier_is_globally_unique(person, source_artifact):
    PersonIdentifier.objects.create(person=person, scheme="nc-sbe", identifier="candidate-123")
    other = Person.objects.create(canonical_name="Another Person", source_artifact=source_artifact)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PersonIdentifier.objects.create(person=other, scheme="nc-sbe", identifier="candidate-123")


@pytest.mark.django_db
def test_human_reviewed_identifier_requires_reviewer_and_timestamp(person, django_user_model):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PersonIdentifier.objects.create(
                person=person,
                scheme="civic-data",
                identifier="nc-person-1",
                verification_method=PersonIdentifier.VerificationMethod.HUMAN_REVIEW,
            )

    reviewer = django_user_model.objects.create_user(username="reviewer")
    identifier = PersonIdentifier.objects.create(
        person=person,
        scheme="civic-data",
        identifier="nc-person-1",
        verification_method=PersonIdentifier.VerificationMethod.HUMAN_REVIEW,
        verified_by=reviewer,
        verified_at=timezone.now(),
    )
    assert identifier.verified_by == reviewer


@pytest.mark.django_db
def test_jurisdiction_rejects_self_parent_and_reversed_active_dates(source_artifact):
    jurisdiction = Jurisdiction.objects.create(
        public_id="nc/county/example",
        name="Example County",
        classification=Jurisdiction.Classification.COUNTY,
        state="NC",
        source_artifact=source_artifact,
    )
    jurisdiction.parent = jurisdiction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            jurisdiction.save()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Jurisdiction.objects.create(
                public_id="nc/county/reversed",
                name="Reversed County",
                classification=Jurisdiction.Classification.COUNTY,
                state="NC",
                active_start=date(2026, 12, 31),
                active_end=date(2026, 1, 1),
                source_artifact=source_artifact,
            )


@pytest.mark.django_db
def test_office_positions_and_contest_vote_for_must_be_positive(jurisdiction, election, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Office.objects.create(
                public_id="nc/invalid-office",
                jurisdiction=jurisdiction,
                canonical_name="Invalid Office",
                role="executive",
                positions=0,
                source_artifact=source_artifact,
            )

    office = Office.objects.create(
        public_id="nc/valid-office",
        jurisdiction=jurisdiction,
        canonical_name="Valid Office",
        role="executive",
        positions=1,
        source_artifact=source_artifact,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Contest.objects.create(
                public_id="nc/invalid-contest",
                election=election,
                office=office,
                vote_for=0,
                source_artifact=source_artifact,
            )


@pytest.mark.django_db
def test_primary_party_and_unexpired_flag_are_part_of_contest_identity(election, office, source_artifact):
    democratic = Contest.objects.create(
        public_id="contest/democratic",
        election=election,
        office=office,
        party_contest="democratic",
        source_artifact=source_artifact,
    )
    republican = Contest.objects.create(
        public_id="contest/republican",
        election=election,
        office=office,
        party_contest="republican",
        source_artifact=source_artifact,
    )
    unexpired = Contest.objects.create(
        public_id="contest/democratic-unexpired",
        election=election,
        office=office,
        party_contest="democratic",
        is_unexpired=True,
        source_artifact=source_artifact,
    )

    assert len({democratic.id, republican.id, unexpired.id}) == 3
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Contest.objects.create(
                public_id="contest/duplicate",
                election=election,
                office=office,
                party_contest="democratic",
                source_artifact=source_artifact,
            )


@pytest.mark.django_db
def test_candidacy_is_unique_per_person_and_contest_and_preserves_ballot_name(
    candidacy,
    person,
    contest,
    source_artifact,
):
    assert candidacy.ballot_name == "DeDreana Freeman"

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Candidacy.objects.create(
                person=person,
                contest=contest,
                ballot_name="Dedreana Freeman",
                source_artifact=source_artifact,
            )


@pytest.mark.django_db
def test_person_source_record_preserves_reported_and_protected_evidence(person, contest, source_artifact):
    record = PersonSourceRecord.objects.create(
        source_artifact=source_artifact,
        source_row_key="candidate-row-1",
        person=person,
        reported_name="DeDreana Freeman",
        ballot_name="DeDreana Freeman",
        given_name="DeDreana",
        family_name="Freeman",
        filing_data={"contest_public_id": contest.public_id},
        protected_address="123 Private Lane",
        protected_phone="919-555-0100",
        protected_email="private@example.test",
        parser_version="nc-candidates-v1",
        retrieval_context={"row_number": 42},
    )

    assert record.reported_name == "DeDreana Freeman"
    assert record.protected_address == "123 Private Lane"
    assert record.retrieval_context == {"row_number": 42}

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PersonSourceRecord.objects.create(
                source_artifact=source_artifact,
                source_row_key="candidate-row-1",
                reported_name="Duplicate row",
                parser_version="nc-candidates-v1",
            )


@pytest.mark.django_db
def test_person_source_evidence_cannot_be_rewritten_but_person_link_can_change(source_artifact):
    record = PersonSourceRecord.objects.create(
        source_artifact=source_artifact,
        source_row_key="candidate-row-immutable",
        reported_name="DeDreana Freeman",
        protected_email="private@example.test",
        parser_version="nc-candidates-v1",
    )
    record.reported_name = "Dedreana Freeman"

    with pytest.raises(ValidationError, match="immutable source fields"):
        record.save()

    resolved = Person.objects.create(
        canonical_name="Dedreana Freeman",
        identity_state=Person.IdentityState.RESOLVED,
        source_artifact=source_artifact,
    )
    record.refresh_from_db()
    record.person = resolved
    record.save()
    assert record.person == resolved


@pytest.mark.django_db
def test_office_term_rejects_end_before_start(person, office, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OfficeTerm.objects.create(
                person=person,
                office=office,
                start_date=date(2027, 1, 1),
                end_date=date(2026, 12, 31),
                method_of_selection=OfficeTerm.SelectionMethod.ELECTION,
                role="member",
                source_artifact=source_artifact,
            )
