from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person
from cm2_results.models import ContestResult


@pytest.fixture
def source_artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        retrieved_at=timezone.now(),
        content_sha256="b" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
    )


@pytest.fixture
def contest(db, source_artifact):
    jurisdiction = Jurisdiction.objects.create(
        public_id="nc/town/harrellsville",
        name="Town of Harrellsville",
        classification=Jurisdiction.Classification.MUNICIPALITY,
        state="NC",
        source_artifact=source_artifact,
    )
    office = Office.objects.create(
        public_id="nc/town/harrellsville/mayor",
        jurisdiction=jurisdiction,
        canonical_name="Mayor",
        role="executive",
        source_artifact=source_artifact,
    )
    election = Election.objects.create(
        public_id="nc/2026-03-03/primary",
        name="2026 Primary Election",
        election_date=date(2026, 3, 3),
        election_type=Election.ElectionType.PRIMARY,
        source_artifact=source_artifact,
    )
    return Contest.objects.create(
        public_id="nc/2026-03-03/primary/harrellsville-mayor",
        election=election,
        office=office,
        source_artifact=source_artifact,
    )


@pytest.fixture
def candidacy(db, contest, source_artifact):
    person = Person.objects.create(canonical_name="Known Candidate", source_artifact=source_artifact)
    return Candidacy.objects.create(
        person=person,
        contest=contest,
        ballot_name="Known Candidate",
        source_artifact=source_artifact,
    )


@pytest.fixture
def contest_result(db, contest, source_artifact):
    return ContestResult.objects.create(
        contest=contest,
        status=ContestResult.Status.UNOFFICIAL,
        source_artifact=source_artifact,
        total_votes=100,
        source_evidence={"status_label": "Election Night Results"},
    )
