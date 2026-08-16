from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person


@pytest.fixture
def source_artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url="https://example.test/nc/candidates.csv",
        retrieved_at=timezone.now(),
        content_sha256="a" * 64,
        parser_version="nc-candidates-v1",
        election_date=date(2026, 11, 3),
    )


@pytest.fixture
def jurisdiction(db, source_artifact):
    return Jurisdiction.objects.create(
        public_id="ocd-division/country:us/state:nc",
        name="North Carolina",
        classification=Jurisdiction.Classification.STATE,
        state="NC",
        record_status=Jurisdiction.RecordStatus.VERIFIED,
        source_artifact=source_artifact,
        source_key="nc",
    )


@pytest.fixture
def office(db, jurisdiction, source_artifact):
    return Office.objects.create(
        public_id="nc/us-senator",
        jurisdiction=jurisdiction,
        canonical_name="United States Senator",
        role="legislator",
        default_term_months=72,
        positions=1,
        record_status=Office.RecordStatus.VERIFIED,
        source_artifact=source_artifact,
        source_key="US SENATE",
    )


@pytest.fixture
def election(db, source_artifact):
    return Election.objects.create(
        public_id="nc/2026-11-03/general",
        name="2026 General Election",
        election_date=date(2026, 11, 3),
        election_type=Election.ElectionType.GENERAL,
        lifecycle_status=Election.LifecycleStatus.UPCOMING,
        source_artifact=source_artifact,
        source_key="2026-11-03-general",
    )


@pytest.fixture
def contest(db, election, office, source_artifact):
    return Contest.objects.create(
        public_id="nc/2026-11-03/general/us-senator",
        election=election,
        office=office,
        vote_for=1,
        is_partisan=True,
        lifecycle_status=Contest.LifecycleStatus.UPCOMING,
        result_status=Contest.ResultStatus.PENDING,
        source_artifact=source_artifact,
        source_key="US SENATE",
    )


@pytest.fixture
def person(db, source_artifact):
    return Person.objects.create(
        canonical_name="DeDreana Freeman",
        given_name="DeDreana",
        family_name="Freeman",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
        source_key="candidate-row-1",
    )


@pytest.fixture
def candidacy(db, person, contest, source_artifact):
    return Candidacy.objects.create(
        person=person,
        contest=contest,
        ballot_name="DeDreana Freeman",
        party_candidate="DEM",
        status=Candidacy.Status.ACTIVE,
        source_artifact=source_artifact,
        source_key="candidate-row-1",
    )
