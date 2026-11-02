import json
from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person, PersonSourceRecord
from cm2_ingestion.contracts import (
    CandidateFilingRecord,
    ContractValidationError,
    IngestionNotice,
    PersonSourceEvidence,
)
from cm2_ingestion.models import ReconciliationReport, SyncLog
from cm2_ingestion.persistence import apply_pre_election_batch
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase


@pytest.mark.django_db
def test_valid_batch_creates_domain_provenance_review_and_aggregate_report(source_artifact, batch_factory):
    report = apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())

    assert Jurisdiction.objects.count() == 1
    assert Office.objects.count() == 1
    assert Election.objects.count() == 1
    assert Contest.objects.count() == 1
    assert Person.objects.count() == 1
    assert PersonSourceRecord.objects.count() == 2
    assert Candidacy.objects.count() == 1
    # No existing person resembles this one, so there is nothing to reconcile:
    # the person is auto-resolved instead of queuing a no-op review case.
    assert IdentityReviewCase.objects.count() == 0
    assert IdentityReviewAuditEvent.objects.filter(event_type=IdentityReviewAuditEvent.EventType.CREATED).count() == 0
    assert report.sync_log.status == SyncLog.Status.SUCCESS
    assert report.sync_log.aggregate_counts == {
        "candidacies_created": 1,
        "candidacies_updated": 0,
        "contests_created": 1,
        "contests_updated": 0,
        "elections_created": 1,
        "elections_updated": 0,
        "jurisdictions_created": 1,
        "jurisdictions_updated": 0,
        "offices_created": 1,
        "offices_updated": 0,
        "people_auto_resolved": 1,
        "people_created": 1,
        "review_cases_created": 0,
        "source_records_created": 2,
    }
    person = Person.objects.get()
    assert person.public_id in report.details["created"]["people"]
    assert person.identity_state == Person.IdentityState.RESOLVED
    assert report.details["review_cases"] == []

    sync_output = json.dumps(report.sync_log.aggregate_counts)
    assert "DeDreana" not in sync_output
    assert "123 Private Lane" not in sync_output
    assert "private@example.test" not in sync_output


@pytest.mark.django_db
def test_new_person_similar_to_existing_creates_fuzzy_match_case_with_suggestion(source_artifact, batch_factory):
    existing = Person.objects.create(
        canonical_name="Dedreana Freeman",
        family_name="Freeman",
        given_name="Dedreana",
        identity_state=Person.IdentityState.RESOLVED,
        source_artifact=source_artifact,
    )

    report = apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())

    review_case = IdentityReviewCase.objects.get()
    assert review_case.case_type == IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH
    suggestion = review_case.suggestions.get()
    assert suggestion.suggested_person == existing
    assert suggestion.rank == 1
    assert report.sync_log.aggregate_counts["review_cases_created"] == 1


@pytest.mark.django_db
def test_successful_artifact_replay_returns_same_report_without_duplicates(source_artifact, batch_factory):
    first = apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())
    counts = {
        "jurisdictions": Jurisdiction.objects.count(),
        "offices": Office.objects.count(),
        "elections": Election.objects.count(),
        "contests": Contest.objects.count(),
        "people": Person.objects.count(),
        "source_records": PersonSourceRecord.objects.count(),
        "candidacies": Candidacy.objects.count(),
        "reviews": IdentityReviewCase.objects.count(),
        "sync_logs": SyncLog.objects.count(),
        "reports": ReconciliationReport.objects.count(),
    }

    second = apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())

    assert second == first
    assert counts == {
        "jurisdictions": Jurisdiction.objects.count(),
        "offices": Office.objects.count(),
        "elections": Election.objects.count(),
        "contests": Contest.objects.count(),
        "people": Person.objects.count(),
        "source_records": PersonSourceRecord.objects.count(),
        "candidacies": Candidacy.objects.count(),
        "reviews": IdentityReviewCase.objects.count(),
        "sync_logs": SyncLog.objects.count(),
        "reports": ReconciliationReport.objects.count(),
    }


@pytest.mark.django_db
def test_election_can_retain_discovery_artifact_and_notices_remain_public_aggregates(
    source_artifact,
    batch_factory,
):
    discovery_artifact = SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.ELECTIONS,
        url="https://example.test/nc/upcoming-elections",
        retrieved_at=source_artifact.retrieved_at,
        content_sha256="a" * 64,
        parser_version="nc-upcoming-v1",
    )
    original = batch_factory()
    election = replace(
        original.elections[0],
        source_artifact_public_id=discovery_artifact.public_id,
    )
    notice = IngestionNotice(
        code="csv_only_election",
        subject_type="election",
        subject_public_id=election.public_id,
    )

    report = apply_pre_election_batch(
        artifact=source_artifact,
        batch=replace(original, elections=(election,), notices=(notice,)),
    )

    assert Election.objects.get().source_artifact == discovery_artifact
    assert Contest.objects.get().source_artifact == source_artifact
    assert Candidacy.objects.get().source_artifact == source_artifact
    assert PersonSourceRecord.objects.filter(source_artifact=source_artifact).count() == 2
    assert report.sync_log.aggregate_counts["notices_csv_only_election"] == 1
    assert report.details["notices"] == [
        {
            "code": "csv_only_election",
            "subject_type": "election",
            "subject_public_id": election.public_id,
        }
    ]


@pytest.mark.django_db
def test_missing_election_artifact_override_rolls_back_domain_batch(source_artifact, batch_factory):
    original = batch_factory()
    election = replace(
        original.elections[0],
        source_artifact_public_id="missing-discovery-artifact",
    )

    with pytest.raises(ContractValidationError, match="source artifact is unavailable"):
        apply_pre_election_batch(
            artifact=source_artifact,
            batch=replace(original, elections=(election,)),
        )

    assert Election.objects.count() == 0
    assert Jurisdiction.objects.count() == 0
    assert Office.objects.count() == 0
    assert Contest.objects.count() == 0
    assert Person.objects.count() == 0
    sync_log = SyncLog.objects.get()
    assert sync_log.status == SyncLog.Status.FAILED
    assert sync_log.error_summary == "ContractValidationError: batch validation failed"


@pytest.mark.django_db
def test_equal_names_without_deterministic_lineage_create_distinct_people(source_artifact, batch_factory):
    first = batch_factory().candidates[0]
    second = CandidateFilingRecord(
        filing_key="us-senator/same-name-second-person",
        contest_public_id=first.contest_public_id,
        ballot_name=first.ballot_name,
        canonical_name=first.canonical_name,
        party_candidate="UNA",
        source_records=(
            PersonSourceEvidence(
                source_row_key="different-person-row",
                reported_name=first.canonical_name,
                ballot_name=first.ballot_name,
            ),
        ),
    )

    apply_pre_election_batch(
        artifact=source_artifact,
        batch=batch_factory(candidates=(first, second)),
    )

    assert Person.objects.filter(canonical_name="DeDreana Freeman").count() == 2
    assert Candidacy.objects.count() == 2
    # The first person has no existing match, so it's auto-resolved with no
    # case; the second person matches the first by name and still gets a
    # fuzzy-match case for a human to reconcile.
    assert IdentityReviewCase.objects.count() == 1
    assert IdentityReviewCase.objects.get().case_type == IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH


@pytest.mark.django_db
def test_prior_source_row_lineage_reuses_person_across_artifact_versions(source_artifact, batch_factory):
    apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())
    original_person = Person.objects.get()
    successor = SourceArtifact.objects.create(
        source_system=source_artifact.source_system,
        source_type=source_artifact.source_type,
        url=source_artifact.url,
        retrieved_at=source_artifact.retrieved_at + timedelta(days=1),
        content_sha256="e" * 64,
        parser_version="nc-candidates-v2",
        election_date=source_artifact.election_date,
        supersedes=source_artifact,
    )

    apply_pre_election_batch(artifact=successor, batch=batch_factory())

    assert Person.objects.count() == 1
    assert Person.objects.get() == original_person
    assert PersonSourceRecord.objects.count() == 4
    assert Candidacy.objects.count() == 1
    assert SyncLog.objects.count() == 2
    assert ReconciliationReport.objects.count() == 2


@pytest.mark.django_db
def test_same_row_key_from_different_source_url_does_not_authorize_person_link(source_artifact, batch_factory):
    apply_pre_election_batch(artifact=source_artifact, batch=batch_factory())
    unrelated_stream = SourceArtifact.objects.create(
        source_system=source_artifact.source_system,
        source_type=source_artifact.source_type,
        url="https://example.test/nc/different-candidates.csv",
        retrieved_at=source_artifact.retrieved_at + timedelta(days=1),
        content_sha256="f" * 64,
        parser_version="different-candidate-source-v1",
        election_date=source_artifact.election_date,
    )

    apply_pre_election_batch(artifact=unrelated_stream, batch=batch_factory())

    assert Person.objects.count() == 2
    assert Candidacy.objects.count() == 2
    # First sync's person has no existing match and is auto-resolved with no
    # case; the second sync's person matches it by name and still gets a
    # fuzzy-match case for a human to reconcile.
    assert IdentityReviewCase.objects.count() == 1
    assert IdentityReviewCase.objects.get().case_type == IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH


@pytest.mark.django_db
def test_invalid_batch_writes_no_domain_entities_and_retains_sanitized_failed_sync(
    source_artifact,
    batch_factory,
):
    invalid_candidate = CandidateFilingRecord(
        filing_key="invalid-private-candidate",
        contest_public_id="missing-contest",
        ballot_name="Private Candidate",
        source_records=(
            PersonSourceEvidence(
                source_row_key="private-row",
                reported_name="Private Candidate",
                protected_address="987 Never Publish Avenue",
                protected_phone="919-555-0199",
                protected_email="never-publish@example.test",
            ),
        ),
    )

    with pytest.raises(ContractValidationError):
        apply_pre_election_batch(
            artifact=source_artifact,
            batch=batch_factory(candidates=(invalid_candidate,)),
        )

    assert Jurisdiction.objects.count() == 0
    assert Office.objects.count() == 0
    assert Election.objects.count() == 0
    assert Contest.objects.count() == 0
    assert Person.objects.count() == 0
    assert PersonSourceRecord.objects.count() == 0
    assert Candidacy.objects.count() == 0
    assert ReconciliationReport.objects.count() == 0
    sync_log = SyncLog.objects.get()
    assert sync_log.status == SyncLog.Status.FAILED
    assert sync_log.aggregate_counts == {}
    assert sync_log.error_summary == "ContractValidationError: batch validation failed"
    assert "Never Publish" not in sync_log.error_summary
    assert "never-publish@example.test" not in sync_log.error_summary


@pytest.mark.django_db
def test_sync_log_rejects_nonaggregate_or_negative_counter_values(source_artifact):
    sync_log = SyncLog(
        run_key="invalid-counts",
        state="NC",
        source_system="nc_sbe",
        capability=SyncLog.Capability.PRE_ELECTION,
        source_artifact=source_artifact,
        aggregate_counts={"candidate_name": "Private Candidate", "bad_count": -1},
        started_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="nonnegative integer"):
        sync_log.full_clean()
