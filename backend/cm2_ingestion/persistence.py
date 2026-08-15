from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import (
    Candidacy,
    Election,
    Person,
    PersonSourceRecord,
)
from cm2_review.matching import find_person_match_candidates, generate_suggestions_for_case
from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import create_review_case

from . import entities
from .contracts import (
    CandidateFilingRecord,
    ContractValidationError,
    PersonSourceEvidence,
    PreElectionBatch,
    validate_pre_election_batch,
)
from .models import ReconciliationReport, SyncLog

_COUNT_KEYS = (
    "candidacies_created",
    "candidacies_updated",
    "contests_created",
    "contests_updated",
    "elections_created",
    "elections_updated",
    "jurisdictions_created",
    "jurisdictions_updated",
    "offices_created",
    "offices_updated",
    "people_created",
    "review_cases_created",
    "source_records_created",
)


def _new_counts() -> dict[str, int]:
    return {key: 0 for key in _COUNT_KEYS}


def _source_artifact_for_record(
    *,
    default_artifact: SourceArtifact,
    source_artifact_public_id: str | None,
) -> SourceArtifact:
    if not source_artifact_public_id:
        return default_artifact
    try:
        return SourceArtifact.objects.get(public_id=source_artifact_public_id)
    except SourceArtifact.DoesNotExist as exc:
        raise ContractValidationError("record source artifact is unavailable") from exc


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, ContractValidationError):
        return "ContractValidationError: batch validation failed"
    return f"{type(exc).__name__}: persistence failed"


def record_pre_election_source_failure(
    *,
    artifact: SourceArtifact,
    state: str,
    exc: Exception,
) -> SyncLog:
    error_summary = f"{type(exc).__name__}: source parsing failed"
    sync_log, _ = SyncLog.objects.update_or_create(
        run_key=f"pre-election:{artifact.public_id}",
        defaults={
            "state": state,
            "source_system": artifact.source_system,
            "capability": SyncLog.Capability.PRE_ELECTION,
            "status": SyncLog.Status.FAILED,
            "source_artifact": artifact,
            "started_at": timezone.now(),
            "completed_at": timezone.now(),
            "aggregate_counts": {},
            "error_summary": error_summary,
        },
    )
    return sync_log


def _follow_person_redirect(person: Person) -> Person:
    seen = set()
    while person.identity_state == Person.IdentityState.MERGED:
        if not person.merged_into_id or person.id in seen:
            raise ContractValidationError("invalid merged Person redirect")
        seen.add(person.id)
        person = person.merged_into
    return person


def _prior_lineage_people(
    *,
    artifact: SourceArtifact,
    evidence_rows: tuple[PersonSourceEvidence, ...],
) -> set[Person]:
    row_keys = [evidence.source_row_key for evidence in evidence_rows]
    source_records = (
        PersonSourceRecord.objects.filter(
            source_artifact__source_system=artifact.source_system,
            source_artifact__url=artifact.url,
            source_row_key__in=row_keys,
            person__isnull=False,
        )
        .select_related("person", "person__merged_into")
        .order_by("-source_artifact__retrieved_at")
    )
    return {_follow_person_redirect(source_record.person) for source_record in source_records}


def _resolve_or_create_person(
    *,
    artifact: SourceArtifact,
    candidate: CandidateFilingRecord,
) -> tuple[Person, bool]:
    lineage_people = _prior_lineage_people(artifact=artifact, evidence_rows=candidate.source_records)
    explicit_person = None
    if candidate.person_public_id:
        explicit_person = Person.objects.filter(public_id=candidate.person_public_id).select_related("merged_into").first()
        if explicit_person:
            explicit_person = _follow_person_redirect(explicit_person)

    resolved_people = set(lineage_people)
    if explicit_person:
        resolved_people.add(explicit_person)
    if len(resolved_people) > 1:
        raise ContractValidationError("candidate filing has conflicting deterministic Person lineage")
    if resolved_people:
        return resolved_people.pop(), False

    values = {
        "canonical_name": candidate.canonical_name or candidate.ballot_name,
        "prefix": candidate.prefix,
        "given_name": candidate.given_name,
        "middle_name": candidate.middle_name,
        "family_name": candidate.family_name,
        "suffix": candidate.suffix,
        "identity_state": Person.IdentityState.PROVISIONAL,
        "source_artifact": artifact,
        "source_key": candidate.filing_key,
    }
    if candidate.person_public_id:
        person = Person.objects.create(public_id=candidate.person_public_id, **values)
    else:
        person = Person.objects.create(**values)
    return person, True


def _source_record_values(
    *,
    artifact: SourceArtifact,
    evidence: PersonSourceEvidence,
    person: Person,
) -> dict:
    return {
        "person": person,
        "reported_name": evidence.reported_name,
        "ballot_name": evidence.ballot_name,
        "prefix": evidence.prefix,
        "given_name": evidence.given_name,
        "middle_name": evidence.middle_name,
        "family_name": evidence.family_name,
        "suffix": evidence.suffix,
        "filing_data": evidence.filing_data or {},
        "protected_address": evidence.protected_address,
        "protected_phone": evidence.protected_phone,
        "protected_email": evidence.protected_email,
        "parser_version": artifact.parser_version,
        "retrieval_context": evidence.retrieval_context or {},
    }


def _persist_source_records(
    *,
    artifact: SourceArtifact,
    candidate: CandidateFilingRecord,
    person: Person,
) -> tuple[list[PersonSourceRecord], int]:
    source_records = []
    created_count = 0
    immutable_fields = set(PersonSourceRecord.IMMUTABLE_SOURCE_FIELDS) - {"source_artifact_id"}
    for evidence in candidate.source_records:
        values = _source_record_values(artifact=artifact, evidence=evidence, person=person)
        source_record, created = PersonSourceRecord.objects.get_or_create(
            source_artifact=artifact,
            source_row_key=evidence.source_row_key,
            defaults=values,
        )
        if created:
            created_count += 1
        else:
            for field_name in immutable_fields:
                if getattr(source_record, field_name) != values[field_name]:
                    raise ContractValidationError("source evidence conflicts with registered artifact row")
            if source_record.person_id and source_record.person_id != person.id:
                raise ContractValidationError("source evidence has conflicting deterministic Person lineage")
            if not source_record.person_id:
                source_record.person = person
                source_record.save(update_fields=["person", "updated_at"])
        source_records.append(source_record)
    return source_records, created_count


def _empty_details() -> dict:
    categories = ("jurisdictions", "offices", "elections", "contests", "people", "candidacies")
    return {
        "created": {category: [] for category in categories},
        "updated": {category: [] for category in categories if category != "people"},
        "review_cases": [],
        "notices": [],
    }


def _persist_batch(*, artifact: SourceArtifact, batch: PreElectionBatch, sync_log: SyncLog) -> ReconciliationReport:
    counts = _new_counts()
    details = _empty_details()
    for notice in batch.notices:
        count_key = f"notices_{notice.code}"
        counts[count_key] = counts.get(count_key, 0) + 1
        details["notices"].append(
            {
                "code": notice.code,
                "subject_type": notice.subject_type,
                "subject_public_id": notice.subject_public_id,
            }
        )
    jurisdictions = entities.persist_jurisdictions(
        artifact=artifact,
        records=batch.jurisdictions,
        counts=counts,
        details=details,
    )

    offices = entities.persist_offices(
        artifact=artifact,
        records=batch.offices,
        jurisdictions=jurisdictions,
        counts=counts,
        details=details,
    )

    elections: dict[str, Election] = {}
    for record in batch.elections:
        election_artifact = _source_artifact_for_record(
            default_artifact=artifact,
            source_artifact_public_id=record.source_artifact_public_id,
        )
        election, created, updated = entities.upsert_public(
            Election,
            record.public_id,
            {
                "name": record.name,
                "election_date": record.election_date,
                "election_type": record.election_type,
                "lifecycle_status": record.lifecycle_status,
                "source_artifact": election_artifact,
                "source_key": record.source_key,
            },
        )
        elections[record.public_id] = election
        entities.track(
            category="elections",
            instance=election,
            created=created,
            updated=updated,
            counts=counts,
            details=details,
        )

    contests = entities.persist_contests(
        artifact=artifact,
        records=batch.contests,
        elections=elections,
        offices=offices,
        counts=counts,
        details=details,
    )

    for candidate in batch.candidates:
        person, person_created = _resolve_or_create_person(artifact=artifact, candidate=candidate)
        if person_created:
            counts["people_created"] += 1
            details["created"]["people"].append(person.public_id)

        source_records, source_record_count = _persist_source_records(
            artifact=artifact,
            candidate=candidate,
            person=person,
        )
        counts["source_records_created"] += source_record_count

        candidacy, created, updated = entities.upsert_natural(
            Candidacy,
            {"person": person, "contest": contests[candidate.contest_public_id]},
            {
                "ballot_name": candidate.ballot_name,
                "party_candidate": candidate.party_candidate,
                "filing_date": candidate.filing_date,
                "status": candidate.status,
                "source_artifact": artifact,
                "source_key": candidate.filing_key,
            },
        )
        candidacy.source_records.add(*source_records)
        entities.track(
            category="candidacies",
            instance=candidacy,
            created=created,
            updated=updated,
            counts=counts,
            details=details,
        )

        if person_created:
            has_private_evidence = any(
                evidence.protected_address or evidence.protected_phone or evidence.protected_email
                for evidence in candidate.source_records
            )
            match_candidates = find_person_match_candidates(
                canonical_name=person.canonical_name,
                family_name=person.family_name,
                exclude_person_id=person.id,
            )
            case_type = (
                IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH
                if match_candidates
                else IdentityReviewCase.CaseType.PERSON_IDENTITY
            )
            review_case, review_created = create_review_case(
                deduplication_key=f"new-person:{artifact.public_id}:{candidate.filing_key}",
                defaults={
                    "case_type": case_type,
                    "source_record": source_records[0],
                    "provisional_person": person,
                    "supporting_evidence": {
                        "source_system": artifact.source_system,
                        "filing_key": candidate.filing_key,
                    },
                    "has_private_evidence": bool(has_private_evidence),
                },
            )
            if review_created:
                counts["review_cases_created"] += 1
                if match_candidates:
                    generate_suggestions_for_case(review_case, match_candidates)
            details["review_cases"].append(review_case.public_id)

    completed_at = timezone.now()
    sync_log.status = SyncLog.Status.SUCCESS
    sync_log.completed_at = completed_at
    sync_log.aggregate_counts = counts
    sync_log.error_summary = ""
    sync_log.save(update_fields=["status", "completed_at", "aggregate_counts", "error_summary", "updated_at"])
    return ReconciliationReport.objects.create(
        sync_log=sync_log,
        source_artifact=artifact,
        details=details,
    )


def apply_pre_election_batch(*, artifact: SourceArtifact, batch: PreElectionBatch) -> ReconciliationReport:
    run_key = f"pre-election:{artifact.public_id}"
    sync_log, _ = SyncLog.objects.get_or_create(
        run_key=run_key,
        defaults={
            "state": batch.state,
            "source_system": artifact.source_system,
            "capability": SyncLog.Capability.PRE_ELECTION,
            "source_artifact": artifact,
            "started_at": timezone.now(),
        },
    )
    if sync_log.status == SyncLog.Status.SUCCESS:
        try:
            return sync_log.report
        except ReconciliationReport.DoesNotExist:
            pass

    SyncLog.objects.filter(pk=sync_log.pk).update(
        state=batch.state,
        source_system=artifact.source_system,
        capability=SyncLog.Capability.PRE_ELECTION,
        status=SyncLog.Status.STARTED,
        source_artifact=artifact,
        started_at=timezone.now(),
        completed_at=None,
        aggregate_counts={},
        error_summary="",
    )
    sync_log.refresh_from_db()

    try:
        validate_pre_election_batch(batch)
        with transaction.atomic():
            return _persist_batch(artifact=artifact, batch=batch, sync_log=sync_log)
    except Exception as exc:
        SyncLog.objects.filter(pk=sync_log.pk).update(
            status=SyncLog.Status.FAILED,
            completed_at=timezone.now(),
            aggregate_counts={},
            error_summary=_safe_error_summary(exc),
        )
        raise
