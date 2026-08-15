import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person, PersonSourceRecord
from cm2_elections.serializers import CandidacySerializer, PersonSerializer
from cm2_ingestion.contracts import ContractValidationError
from cm2_ingestion.models import ReconciliationReport, SyncLog
from cm2_nc.ingest import ingest_nc_pre_election_contents
from cm2_review.models import IdentityReviewCase

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_content():
    return {
        "upcoming_content": (FIXTURES / "upcoming_elections_2026.html").read_bytes(),
        "candidate_content": (FIXTURES / "candidate_listing_2026_sanitized.csv").read_bytes(),
    }


def row_counts():
    return {
        "artifacts": SourceArtifact.objects.count(),
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
def test_nc_fixture_ingests_complete_private_safe_normalized_dataset():
    report = ingest_nc_pre_election_contents(
        **fixture_content(),
        retrieved_at=timezone.now(),
    )

    assert row_counts() == {
        "artifacts": 2,
        "jurisdictions": 9,
        "offices": 8,
        "elections": 3,
        "contests": 10,
        "people": 10,
        "source_records": 12,
        "candidacies": 10,
        "reviews": 10,
        "sync_logs": 1,
        "reports": 1,
    }
    discovery_artifact = SourceArtifact.objects.get(source_type=SourceArtifact.SourceType.ELECTIONS)
    candidate_artifact = SourceArtifact.objects.get(source_type=SourceArtifact.SourceType.CANDIDATES)
    assert discovery_artifact.processing_status == SourceArtifact.ProcessingStatus.APPLIED
    assert candidate_artifact.processing_status == SourceArtifact.ProcessingStatus.APPLIED
    assert Election.objects.filter(source_artifact=discovery_artifact).count() == 2
    assert Election.objects.filter(source_artifact=candidate_artifact).count() == 1
    assert report.sync_log.aggregate_counts["notices_csv_only_election"] == 1
    assert report.sync_log.aggregate_counts["notices_measure_excluded"] == 1
    assert {notice["code"] for notice in report.details["notices"]} == {
        "csv_only_election",
        "measure_excluded",
    }

    source_record = PersonSourceRecord.objects.exclude(protected_email="").first()
    assert source_record.protected_address.startswith("REDACTED ADDRESS")
    assert source_record.protected_email.endswith("@example.invalid")
    public_output = json.dumps(
        {
            "person": PersonSerializer(source_record.person).data,
            "candidacy": CandidacySerializer(source_record.candidacies.first()).data,
            "sync": report.sync_log.aggregate_counts,
            "report": report.details,
        }
    )
    assert "REDACTED ADDRESS" not in public_output
    assert "@example.invalid" not in public_output
    assert "0000000000" not in public_output

    legacy_tables = {
        "elections_election",
        "elections_race",
        "elections_candidate",
        "results_officialresult",
    }
    assert legacy_tables.isdisjoint(connection.introspection.table_names())


@pytest.mark.django_db
def test_identical_content_replay_returns_same_report_without_duplicates():
    retrieved_at = timezone.now()
    first = ingest_nc_pre_election_contents(**fixture_content(), retrieved_at=retrieved_at)
    counts = row_counts()

    second = ingest_nc_pre_election_contents(
        **fixture_content(),
        retrieved_at=retrieved_at + timedelta(hours=1),
    )

    assert second == first
    assert row_counts() == counts


@pytest.mark.django_db
def test_changed_private_evidence_creates_successor_records_but_reuses_people():
    retrieved_at = timezone.now()
    contents = fixture_content()
    ingest_nc_pre_election_contents(**contents, retrieved_at=retrieved_at)
    changed = contents["candidate_content"].replace(
        b"redacted1@example.invalid",
        b"changed01@example.invalid",
    )

    ingest_nc_pre_election_contents(
        upcoming_content=contents["upcoming_content"],
        candidate_content=changed,
        retrieved_at=retrieved_at + timedelta(days=1),
    )

    assert SourceArtifact.objects.count() == 3
    candidate_artifacts = SourceArtifact.objects.filter(source_type=SourceArtifact.SourceType.CANDIDATES).order_by(
        "retrieved_at"
    )
    assert candidate_artifacts[1].supersedes == candidate_artifacts[0]
    assert Person.objects.count() == 10
    assert Candidacy.objects.count() == 10
    assert PersonSourceRecord.objects.count() == 24
    assert IdentityReviewCase.objects.count() == 10
    assert SyncLog.objects.count() == 2
    assert ReconciliationReport.objects.count() == 2


@pytest.mark.django_db
def test_parser_failure_writes_sanitized_failed_sync_without_domain_rows():
    private_value = b"never-publish@example.test"
    invalid_candidates = b"election_dt,email\nnot-a-date," + private_value + b"\n"

    with pytest.raises(ContractValidationError):
        ingest_nc_pre_election_contents(
            upcoming_content=(FIXTURES / "upcoming_elections_2026.html").read_bytes(),
            candidate_content=invalid_candidates,
            retrieved_at=timezone.now(),
        )

    assert Election.objects.count() == 0
    assert Jurisdiction.objects.count() == 0
    assert Office.objects.count() == 0
    assert Contest.objects.count() == 0
    assert Person.objects.count() == 0
    sync_log = SyncLog.objects.get()
    assert sync_log.status == SyncLog.Status.FAILED
    assert sync_log.error_summary == "ContractValidationError: source parsing failed"
    assert private_value.decode() not in sync_log.error_summary
    candidate_artifact = SourceArtifact.objects.get(source_type=SourceArtifact.SourceType.CANDIDATES)
    assert candidate_artifact.processing_status == SourceArtifact.ProcessingStatus.FAILED
    assert private_value.decode() not in candidate_artifact.error
