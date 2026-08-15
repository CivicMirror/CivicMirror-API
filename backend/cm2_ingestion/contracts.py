import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


class ContractValidationError(ValueError):
    """Raised when normalized records are structurally unsafe to persist."""


_NOTICE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class IngestionNotice:
    code: str
    subject_type: str
    subject_public_id: str


@dataclass(frozen=True, slots=True)
class ElectionRecord:
    public_id: str
    name: str
    election_date: date
    election_type: str
    lifecycle_status: str = "provisional"
    source_key: str = ""
    source_artifact_public_id: str | None = None


@dataclass(frozen=True, slots=True)
class JurisdictionRecord:
    public_id: str
    name: str
    classification: str
    state: str
    parent_public_id: str | None = None
    active_start: date | None = None
    active_end: date | None = None
    record_status: str = "provisional"
    source_key: str = ""


@dataclass(frozen=True, slots=True)
class OfficeRecord:
    public_id: str
    jurisdiction_public_id: str
    canonical_name: str
    role: str
    default_term_months: int | None = None
    positions: int = 1
    record_status: str = "provisional"
    source_key: str = ""


@dataclass(frozen=True, slots=True)
class ContestRecord:
    public_id: str
    election_public_id: str
    office_public_id: str
    party_contest: str = ""
    vote_for: int = 1
    is_partisan: bool = False
    is_unexpired: bool = False
    lifecycle_status: str = "provisional"
    result_status: str = "pending"
    source_key: str = ""


@dataclass(frozen=True, slots=True)
class PersonSourceEvidence:
    source_row_key: str
    reported_name: str
    ballot_name: str = ""
    prefix: str = ""
    given_name: str = ""
    middle_name: str = ""
    family_name: str = ""
    suffix: str = ""
    filing_data: dict | None = None
    protected_address: str = ""
    protected_phone: str = ""
    protected_email: str = ""
    retrieval_context: dict | None = None


@dataclass(frozen=True, slots=True)
class CandidateFilingRecord:
    filing_key: str
    contest_public_id: str
    ballot_name: str
    source_records: tuple[PersonSourceEvidence, ...]
    person_public_id: str | None = None
    canonical_name: str = ""
    prefix: str = ""
    given_name: str = ""
    middle_name: str = ""
    family_name: str = ""
    suffix: str = ""
    party_candidate: str = ""
    filing_date: date | None = None
    status: str = "active"


@dataclass(frozen=True, slots=True)
class PreElectionBatch:
    state: str
    jurisdictions: tuple[JurisdictionRecord, ...] = ()
    offices: tuple[OfficeRecord, ...] = ()
    elections: tuple[ElectionRecord, ...] = ()
    contests: tuple[ContestRecord, ...] = ()
    candidates: tuple[CandidateFilingRecord, ...] = ()
    notices: tuple[IngestionNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class PrecinctResultObservation:
    source_observation_key: str
    contest_public_id: str
    source_choice_key: str
    source_label: str
    normalized_label: str
    choice_type: str
    vote_total: int
    precinct: str = ""
    voting_method: str = ""


@dataclass(frozen=True, slots=True)
class AggregatedResultChoice:
    contest_public_id: str
    source_choice_key: str
    source_label: str
    normalized_label: str
    choice_type: str
    vote_total: int
    percentage: Decimal
    observation_count: int
    observation_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CertificationEvidence:
    contest_public_id: str
    status: str
    source_label: str
    certified_at: datetime | None = None


def _unique_keys(records, attribute: str, label: str) -> set[str]:
    keys = [getattr(record, attribute) for record in records]
    if any(not key for key in keys):
        raise ContractValidationError(f"{label} keys must be non-empty")
    if len(keys) != len(set(keys)):
        raise ContractValidationError(f"duplicate {label} {attribute}")
    return set(keys)


def _validate_jurisdiction_hierarchy(records: tuple[JurisdictionRecord, ...], public_ids: set[str]) -> None:
    parents = {record.public_id: record.parent_public_id for record in records}
    for record in records:
        if record.parent_public_id and record.parent_public_id not in public_ids:
            raise ContractValidationError("jurisdiction references unknown parent jurisdiction")
        if record.parent_public_id == record.public_id:
            raise ContractValidationError("jurisdiction cannot parent itself")
        if record.active_start and record.active_end and record.active_end < record.active_start:
            raise ContractValidationError("jurisdiction active dates are reversed")

    for public_id in public_ids:
        visited: set[str] = set()
        current: str | None = public_id
        while current:
            if current in visited:
                raise ContractValidationError("jurisdiction parent cycle detected")
            visited.add(current)
            current = parents.get(current)


def validate_pre_election_batch(batch: PreElectionBatch) -> None:
    if len(batch.state) != 2 or batch.state != batch.state.upper():
        raise ContractValidationError("batch state must be an uppercase two-letter code")

    jurisdiction_ids = _unique_keys(batch.jurisdictions, "public_id", "jurisdiction")
    office_ids = _unique_keys(batch.offices, "public_id", "office")
    election_ids = _unique_keys(batch.elections, "public_id", "election")
    contest_ids = _unique_keys(batch.contests, "public_id", "contest")
    _unique_keys(batch.candidates, "filing_key", "candidate filing")
    _validate_jurisdiction_hierarchy(batch.jurisdictions, jurisdiction_ids)

    notice_keys: set[tuple[str, str, str]] = set()
    for notice in batch.notices:
        if not _NOTICE_CODE_RE.fullmatch(notice.code):
            raise ContractValidationError("ingestion notice code is invalid")
        if not notice.subject_type:
            raise ContractValidationError("ingestion notice subject type must be non-empty")
        if not notice.subject_public_id:
            raise ContractValidationError("ingestion notice subject public ID must be non-empty")
        notice_key = (notice.code, notice.subject_type, notice.subject_public_id)
        if notice_key in notice_keys:
            raise ContractValidationError("duplicate ingestion notice")
        notice_keys.add(notice_key)

    for jurisdiction in batch.jurisdictions:
        if jurisdiction.state != batch.state:
            raise ContractValidationError("jurisdiction state does not match batch state")

    for office in batch.offices:
        if office.jurisdiction_public_id not in jurisdiction_ids:
            raise ContractValidationError("office references unknown jurisdiction")
        if office.positions <= 0:
            raise ContractValidationError("office positions must be positive")
        if office.default_term_months is not None and office.default_term_months <= 0:
            raise ContractValidationError("office default term must be positive")

    for contest in batch.contests:
        if contest.election_public_id not in election_ids:
            raise ContractValidationError("contest references unknown election")
        if contest.office_public_id not in office_ids:
            raise ContractValidationError("contest references unknown office")
        if contest.vote_for <= 0:
            raise ContractValidationError("contest vote_for must be positive")

    source_row_keys: set[str] = set()
    for candidate in batch.candidates:
        if candidate.contest_public_id not in contest_ids:
            raise ContractValidationError("candidate filing references unknown contest")
        if not candidate.source_records:
            raise ContractValidationError("candidate filing requires source evidence")
        for evidence in candidate.source_records:
            if not evidence.source_row_key:
                raise ContractValidationError("source row key must be non-empty")
            if evidence.source_row_key in source_row_keys:
                raise ContractValidationError("duplicate source row key")
            source_row_keys.add(evidence.source_row_key)
