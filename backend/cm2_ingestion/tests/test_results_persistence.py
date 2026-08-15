from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person
from cm2_ingestion.contracts import (
    ContestRecord,
    JurisdictionRecord,
    OfficeRecord,
    PostElectionBatch,
    PrecinctResultObservation,
)
from cm2_ingestion.results_persistence import apply_post_election_batch
from cm2_results.models import ContestResult, ResultChoice
from cm2_review.models import IdentityReviewCase


@pytest.fixture
def artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        retrieved_at=timezone.now(),
        content_sha256="e" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
    )


@pytest.fixture
def existing_contest(db):
    jurisdiction = Jurisdiction.objects.create(
        public_id="nc/jurisdiction/state",
        name="North Carolina",
        classification="state",
        state="NC",
        record_status="verified",
    )
    office = Office.objects.create(
        public_id="nc/office/us-senator",
        jurisdiction=jurisdiction,
        canonical_name="U.S. Senator",
        role="senator",
    )
    election = Election.objects.create(
        public_id="nc/election/2026-03-03/primary",
        name="2026 Primary",
        election_date=date(2026, 3, 3),
        election_type="primary",
        lifecycle_status="active",
    )
    contest = Contest.objects.create(
        public_id="nc/contest/us-senator-rep",
        election=election,
        office=office,
        party_contest="REP",
        vote_for=1,
        is_partisan=True,
    )
    return contest


@pytest.fixture
def existing_candidacy(existing_contest):
    person = Person.objects.create(canonical_name="Elizabeth A. Temple", family_name="Temple")
    return Candidacy.objects.create(
        person=person,
        contest=existing_contest,
        ballot_name="Elizabeth A. Temple",
        party_candidate="REP",
    )


def _batch(contest: Contest, *observations: PrecinctResultObservation) -> PostElectionBatch:
    jurisdiction = contest.office.jurisdiction
    jurisdiction_record = JurisdictionRecord(
        public_id=jurisdiction.public_id,
        name=jurisdiction.name,
        classification=jurisdiction.classification,
        state=jurisdiction.state,
        record_status=jurisdiction.record_status,
    )
    office_record = OfficeRecord(
        public_id=contest.office.public_id,
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name=contest.office.canonical_name,
        role=contest.office.role,
        positions=contest.office.positions,
        record_status=contest.office.record_status,
    )
    contest_record = ContestRecord(
        public_id=contest.public_id,
        election_public_id=contest.election.public_id,
        office_public_id=contest.office.public_id,
        party_contest=contest.party_contest,
        vote_for=contest.vote_for,
        is_partisan=contest.is_partisan,
    )
    return PostElectionBatch(
        state="NC",
        new_jurisdictions=(jurisdiction_record,),
        new_offices=(office_record,),
        new_contests=(contest_record,),
        observations=observations,
    )


@pytest.mark.django_db
def test_exact_name_match_links_result_choice_to_existing_candidacy(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    result = ContestResult.objects.get(contest=existing_contest)
    assert result.status == ContestResult.Status.UNOFFICIAL
    assert result.total_votes == 33
    choice = result.choices.get()
    assert choice.resolution_status == ResultChoice.ResolutionStatus.MATCHED
    assert choice.candidacy_id == existing_candidacy.id
    assert choice.is_winner is None


@pytest.mark.django_db
def test_unmatched_candidate_creates_provisional_person_candidacy_and_review_case(artifact, existing_contest):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-2",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-newcomer",
            source_label="Pat Newcomer",
            normalized_label="pat newcomer",
            choice_type="candidate",
            choice_party="REP",
            vote_total=10,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    choice = ResultChoice.objects.get()
    assert choice.resolution_status == ResultChoice.ResolutionStatus.PROVISIONAL
    assert choice.candidacy is not None
    assert choice.candidacy.person.canonical_name == "Pat Newcomer"
    assert choice.candidacy.status == Candidacy.Status.PROVISIONAL
    assert IdentityReviewCase.objects.filter(provisional_person=choice.candidacy.person).exists()


@pytest.mark.django_db
def test_named_write_in_creates_unresolved_choice_and_review_case_without_candidacy(artifact, existing_contest):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-3",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-writein",
            source_label="Jamie Ager (Write-In)",
            normalized_label="jamie ager",
            choice_type="named_write_in",
            vote_total=2,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    choice = ResultChoice.objects.get()
    assert choice.choice_type == ResultChoice.ChoiceType.NAMED_WRITE_IN
    assert choice.resolution_status == ResultChoice.ResolutionStatus.UNRESOLVED
    assert choice.candidacy is None
    assert Candidacy.objects.count() == 0
    assert IdentityReviewCase.objects.filter(
        case_type=IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
        result_choice=choice,
    ).exists()


@pytest.mark.django_db
def test_anonymous_write_in_bucket_is_not_applicable_and_counts_toward_total(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-4",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
        PrecinctResultObservation(
            source_observation_key="obs-5",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-misc",
            source_label="Write-In (Miscellaneous)",
            normalized_label="write-in",
            choice_type="write_in_aggregate",
            vote_total=1,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    result = ContestResult.objects.get(contest=existing_contest)
    assert result.total_votes == 34
    misc = ResultChoice.objects.get(source_label="Write-In (Miscellaneous)")
    assert misc.choice_type == ResultChoice.ChoiceType.WRITE_IN_AGGREGATE
    assert misc.resolution_status == ResultChoice.ResolutionStatus.NOT_APPLICABLE
    assert misc.candidacy is None


@pytest.mark.django_db
def test_replaying_the_same_artifact_returns_the_existing_report(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    first = apply_post_election_batch(artifact=artifact, batch=batch)
    second = apply_post_election_batch(artifact=artifact, batch=batch)
    assert first.pk == second.pk
    assert ResultChoice.objects.count() == 1


@pytest.mark.django_db
def test_correction_updates_vote_totals_without_deleting_choices(artifact, existing_contest, existing_candidacy):
    first_batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=first_batch)

    corrected_artifact = SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url=artifact.url,
        retrieved_at=timezone.now(),
        content_sha256="f" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
        supersedes=artifact,
    )
    second_batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1-corrected",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=40,
        ),
    )
    apply_post_election_batch(artifact=corrected_artifact, batch=second_batch)

    assert ResultChoice.objects.count() == 1
    choice = ResultChoice.objects.get()
    assert choice.vote_total == 40
