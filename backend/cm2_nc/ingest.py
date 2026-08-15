from datetime import date, datetime

from cm2_core.models import SourceArtifact
from cm2_elections.models import Election
from cm2_ingestion.artifacts import register_source_artifact
from cm2_ingestion.contracts import ElectionRecord
from cm2_ingestion.models import ReconciliationReport, SyncLog
from cm2_ingestion.persistence import apply_pre_election_batch, record_pre_election_source_failure
from cm2_ingestion.results_persistence import apply_post_election_batch

from .constants import (
    CANDIDATE_LIST_URL,
    CANDIDATE_PARSER_VERSION,
    RESULTS_PARSER_VERSION,
    SOURCE_SYSTEM,
    UPCOMING_ELECTIONS_URL,
    UPCOMING_PARSER_VERSION,
)
from .sources.candidate_filings import NcCandidateFilingsSource
from .sources.results import NcResultsZipSource, results_zip_url
from .sources.upcoming_elections import parse_upcoming_elections


def _set_artifact_status(artifact: SourceArtifact, status: str, *, error: str = "") -> None:
    SourceArtifact.objects.filter(pk=artifact.pk).update(processing_status=status, error=error)
    artifact.processing_status = status
    artifact.error = error


def _existing_successful_report(candidate_artifact: SourceArtifact) -> ReconciliationReport | None:
    sync_log = SyncLog.objects.filter(
        run_key=f"pre-election:{candidate_artifact.public_id}",
        status=SyncLog.Status.SUCCESS,
    ).first()
    if sync_log is None:
        return None
    try:
        return sync_log.report
    except ReconciliationReport.DoesNotExist:
        return None


def _sanitized_artifact_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: source parsing failed"


def ingest_nc_pre_election_contents(
    *,
    upcoming_content: bytes,
    candidate_content: bytes,
    retrieved_at: datetime,
    upcoming_url: str = UPCOMING_ELECTIONS_URL,
    candidate_url: str = CANDIDATE_LIST_URL,
) -> ReconciliationReport:
    discovery_artifact, _ = register_source_artifact(
        source_system=SOURCE_SYSTEM,
        source_type=SourceArtifact.SourceType.ELECTIONS,
        url=upcoming_url,
        content=upcoming_content,
        retrieved_at=retrieved_at,
        parser_version=UPCOMING_PARSER_VERSION,
    )
    candidate_artifact, _ = register_source_artifact(
        source_system=SOURCE_SYSTEM,
        source_type=SourceArtifact.SourceType.CANDIDATES,
        url=candidate_url,
        content=candidate_content,
        retrieved_at=retrieved_at,
        parser_version=CANDIDATE_PARSER_VERSION,
    )

    existing_report = _existing_successful_report(candidate_artifact)
    if existing_report is not None:
        return existing_report

    try:
        discovered_elections = parse_upcoming_elections(
            upcoming_content,
            source_artifact_public_id=discovery_artifact.public_id,
        )
    except Exception as exc:
        _set_artifact_status(
            discovery_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=_sanitized_artifact_error(exc),
        )
        record_pre_election_source_failure(artifact=candidate_artifact, state="NC", exc=exc)
        raise
    _set_artifact_status(discovery_artifact, SourceArtifact.ProcessingStatus.VALIDATED)

    try:
        batch = NcCandidateFilingsSource().parse(
            candidate_content,
            discovered_elections=discovered_elections,
        )
    except Exception as exc:
        _set_artifact_status(
            candidate_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=_sanitized_artifact_error(exc),
        )
        record_pre_election_source_failure(artifact=candidate_artifact, state="NC", exc=exc)
        raise

    _set_artifact_status(candidate_artifact, SourceArtifact.ProcessingStatus.VALIDATED)
    try:
        report = apply_pre_election_batch(artifact=candidate_artifact, batch=batch)
    except Exception as exc:
        _set_artifact_status(
            candidate_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=f"{type(exc).__name__}: batch application failed",
        )
        raise

    _set_artifact_status(discovery_artifact, SourceArtifact.ProcessingStatus.APPLIED)
    _set_artifact_status(candidate_artifact, SourceArtifact.ProcessingStatus.APPLIED)
    return report


def _existing_successful_results_report(results_artifact: SourceArtifact) -> ReconciliationReport | None:
    sync_log = SyncLog.objects.filter(
        run_key=f"results:{results_artifact.public_id}",
        status=SyncLog.Status.SUCCESS,
    ).first()
    if sync_log is None:
        return None
    try:
        return sync_log.report
    except ReconciliationReport.DoesNotExist:
        return None


def _elections_for_date(election_date: date) -> tuple[ElectionRecord, ...]:
    return tuple(
        ElectionRecord(
            public_id=election.public_id,
            name=election.name,
            election_date=election.election_date,
            election_type=election.election_type,
            lifecycle_status=election.lifecycle_status,
        )
        for election in Election.objects.filter(election_date=election_date)
    )


def ingest_nc_post_election_contents(
    *,
    results_content: bytes,
    election_date: date,
    retrieved_at: datetime,
    results_url: str | None = None,
) -> ReconciliationReport:
    url = results_url or results_zip_url(election_date)
    results_artifact, _ = register_source_artifact(
        source_system=SOURCE_SYSTEM,
        source_type=SourceArtifact.SourceType.RESULTS,
        url=url,
        content=results_content,
        retrieved_at=retrieved_at,
        parser_version=RESULTS_PARSER_VERSION,
        election_date=election_date,
    )

    existing_report = _existing_successful_results_report(results_artifact)
    if existing_report is not None:
        return existing_report

    try:
        source = NcResultsZipSource(election_date=election_date)
        batch = source.parse(results_content, existing_elections=_elections_for_date(election_date))
    except Exception as exc:
        _set_artifact_status(
            results_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=_sanitized_artifact_error(exc),
        )
        raise

    _set_artifact_status(results_artifact, SourceArtifact.ProcessingStatus.VALIDATED)
    try:
        report = apply_post_election_batch(artifact=results_artifact, batch=batch)
    except Exception as exc:
        _set_artifact_status(
            results_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=f"{type(exc).__name__}: batch application failed",
        )
        raise

    _set_artifact_status(results_artifact, SourceArtifact.ProcessingStatus.APPLIED)
    return report
