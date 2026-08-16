import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person, PersonSourceRecord
from cm2_elections.serializers import CandidacySerializer, PersonSerializer
from cm2_ingestion.contracts import ContractValidationError
from cm2_ingestion.models import ReconciliationReport, SyncLog
from cm2_nc.ingest import ingest_nc_post_election_contents, ingest_nc_pre_election_contents
from cm2_results.models import ContestResult, ResultChoice
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


def _results_zip_bytes() -> bytes:
    text = (FIXTURES / "results_pct_sanitized.txt").read_text()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # Pin the entry timestamp: zipfile defaults to "now" (2-second resolution), which would make the
        # bytes -- and therefore the artifact content hash -- differ between calls and break replay tests.
        archive.writestr(zipfile.ZipInfo("results_pct_20260303.txt", date_time=(2026, 3, 3, 0, 0, 0)), text)
    return buffer.getvalue()


@pytest.mark.django_db
def test_nc_post_election_ingestion_persists_results_for_existing_election():
    ingest_nc_pre_election_contents(**fixture_content(), retrieved_at=timezone.now())
    election = Election.objects.filter(election_date=date(2026, 3, 3)).first()
    if election is None:
        election = Election.objects.create(
            public_id="nc/election/2026-03-03/primary",
            name="2026 North Carolina Primary",
            election_date=date(2026, 3, 3),
            election_type="primary",
            lifecycle_status="active",
        )

    results_report = ingest_nc_post_election_contents(
        results_content=_results_zip_bytes(),
        election_date=date(2026, 3, 3),
        retrieved_at=timezone.now(),
    )

    assert isinstance(results_report, ReconciliationReport)
    assert SourceArtifact.objects.filter(source_type=SourceArtifact.SourceType.RESULTS).exists()
    assert ContestResult.objects.exists()
    assert ResultChoice.objects.exists()

    replay = ingest_nc_post_election_contents(
        results_content=_results_zip_bytes(),
        election_date=date(2026, 3, 3),
        retrieved_at=timezone.now(),
    )
    assert replay.pk == results_report.pk


@pytest.mark.django_db
def test_nc_post_election_ingestion_preserves_pre_election_owned_contest_fields():
    pre_report = ingest_nc_pre_election_contents(**fixture_content(), retrieved_at=timezone.now())
    assert pre_report is not None
    election = Election.objects.filter(election_date=date(2026, 3, 3)).first()
    if election is None:
        election = Election.objects.create(
            public_id="nc/election/2026-03-03/primary",
            name="2026 North Carolina Primary",
            election_date=date(2026, 3, 3),
            election_type="primary",
            lifecycle_status="active",
        )

    before = {
        contest.public_id: (
            contest.source_key,
            contest.source_artifact_id,
            contest.lifecycle_status,
            contest.result_status,
        )
        for contest in Contest.objects.all()
    }
    assert before

    results_report = ingest_nc_post_election_contents(
        results_content=_results_zip_bytes(),
        election_date=date(2026, 3, 3),
        retrieved_at=timezone.now(),
    )

    after = {
        contest.public_id: (
            contest.source_key,
            contest.source_artifact_id,
            contest.lifecycle_status,
            contest.result_status,
        )
        for contest in Contest.objects.filter(public_id__in=before)
    }
    assert after == before

    # The check above is only meaningful if the results file actually landed on a pre-existing contest.
    assert ContestResult.objects.filter(contest__public_id__in=before).exists()

    result_only = results_report.details["result_only_contests"]
    assert result_only
    assert set(result_only).isdisjoint(before)
    assert set(result_only) <= set(Contest.objects.values_list("public_id", flat=True))
    assert ContestResult.objects.filter(contest__public_id__in=result_only).exists()
