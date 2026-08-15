from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Person, PersonSourceRecord


@pytest.fixture
def source_artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url="https://example.test/nc/candidates.csv",
        retrieved_at=timezone.now(),
        content_sha256="c" * 64,
        parser_version="nc-candidates-v1",
        election_date=date(2026, 11, 3),
    )


@pytest.fixture
def provisional_person(db, source_artifact):
    return Person.objects.create(
        canonical_name="DeDreana Freeman",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )


@pytest.fixture
def source_record(db, source_artifact, provisional_person):
    return PersonSourceRecord.objects.create(
        source_artifact=source_artifact,
        source_row_key="candidate-row-1",
        person=provisional_person,
        reported_name="DeDreana Freeman",
        ballot_name="DeDreana Freeman",
        protected_address="123 Private Lane",
        protected_phone="919-555-0100",
        protected_email="private@example.test",
        parser_version="nc-candidates-v1",
    )
