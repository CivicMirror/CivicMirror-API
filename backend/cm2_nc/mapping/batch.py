import hashlib
from collections import Counter, defaultdict
from datetime import date

from cm2_ingestion.contracts import (
    CandidateFilingRecord,
    ContestRecord,
    ContractValidationError,
    ElectionRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PersonSourceEvidence,
    PreElectionBatch,
    validate_pre_election_batch,
)
from cm2_nc.source_records import NcCandidateRow

from .identity import contest_public_id, normalize_identity_part, stable_public_id
from .jurisdictions import map_jurisdiction
from .measures import is_measure_contest
from .offices import map_office


def _put_unique(records: dict[str, object], record, *, label: str) -> None:
    existing = records.get(record.public_id)
    if existing is not None and existing != record:
        raise ContractValidationError(f"conflicting normalized {label} mapping")
    records[record.public_id] = record


def _explicit_candidate_election_type(rows: list[NcCandidateRow]) -> str | None:
    if any(row.party_contest or row.has_primary for row in rows):
        return "primary"
    return None


def _csv_only_election(election_date: date, election_type: str) -> ElectionRecord:
    public_id = stable_public_id("election", election_date.isoformat(), election_type, "candidate-list")
    type_label = "Primary Election" if election_type == "primary" else "Election"
    return ElectionRecord(
        public_id=public_id,
        name=f"North Carolina {type_label} - {election_date.isoformat()}",
        election_date=election_date,
        election_type=election_type,
        lifecycle_status="provisional",
        source_key=f"candidate-list:{election_date.isoformat()}:{election_type}",
    )


def _select_election(
    *,
    rows: list[NcCandidateRow],
    discovered_by_date: dict[date, list[ElectionRecord]],
) -> tuple[ElectionRecord, bool]:
    election_date = rows[0].election_date
    discovered = discovered_by_date.get(election_date, [])
    explicit_type = _explicit_candidate_election_type(rows)
    if explicit_type:
        matching = [record for record in discovered if record.election_type == explicit_type]
        if len(matching) == 1:
            return matching[0], False
        if len(matching) > 1:
            raise ContractValidationError("candidate date matches multiple discovered elections")
        return _csv_only_election(election_date, explicit_type), True

    if len(discovered) == 1:
        return discovered[0], False
    if len(discovered) > 1:
        general = [record for record in discovered if record.election_type == "general"]
        if len(general) == 1:
            return general[0], False
        raise ContractValidationError("candidate date has ambiguous discovered election")
    return _csv_only_election(election_date, "other"), True


def _measure_notice(rows: list[NcCandidateRow]) -> IngestionNotice:
    first = rows[0]
    identity = "\x1f".join(
        (
            first.election_date.isoformat(),
            normalize_identity_part(first.contest_name),
            first.party_contest,
        )
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return IngestionNotice(
        code="measure_excluded",
        subject_type="source_contest",
        subject_public_id=f"nc/source-contest/{digest}",
    )


def _reported_name(row: NcCandidateRow) -> str:
    full_name = " ".join(
        part for part in (row.first_name, row.middle_name, row.last_name, row.suffix) if part
    )
    return full_name or row.name_on_ballot


def _contest_key(row: NcCandidateRow, *, election: ElectionRecord, office: OfficeRecord) -> str:
    return contest_public_id(
        election_public_id=election.public_id,
        office_public_id=office.public_id,
        party_contest=row.party_contest,
        is_unexpired=row.is_unexpired,
    )


def _source_row_base_key(row: NcCandidateRow) -> str:
    filing_date = row.filing_date.isoformat() if row.filing_date else ""
    return stable_public_id(
        "source-row",
        row.election_date.isoformat(),
        row.county_name,
        row.contest_name,
        row.party_contest,
        row.party_candidate,
        row.name_on_ballot,
        row.first_name,
        row.middle_name,
        row.last_name,
        row.suffix,
        filing_date,
    )


def _source_evidence(
    row: NcCandidateRow,
    *,
    contest_public_id: str,
    source_row_key: str,
) -> PersonSourceEvidence:
    return PersonSourceEvidence(
        source_row_key=source_row_key,
        reported_name=_reported_name(row),
        ballot_name=row.name_on_ballot,
        given_name=row.first_name,
        middle_name=row.middle_name,
        family_name=row.last_name,
        suffix=row.suffix,
        filing_data={
            "contest_public_id": contest_public_id,
            "county_name": row.county_name,
            "nickname": row.nickname,
            "party_contest": row.party_contest,
            "party_candidate": row.party_candidate,
            "is_unexpired": row.is_unexpired,
            "has_primary": row.has_primary,
            "is_partisan": row.is_partisan,
            "vote_for": row.vote_for,
            "term_years": row.term_years,
        },
        protected_address=row.protected_address,
        protected_phone=row.protected_phone,
        protected_email=row.protected_email,
        retrieval_context={"row_number": row.row_number, "county_name": row.county_name},
    )


def _candidate_group_key(row: NcCandidateRow, contest_public_id: str) -> tuple[str, ...]:
    return (
        contest_public_id,
        normalize_identity_part(row.name_on_ballot),
        normalize_identity_part(row.first_name),
        normalize_identity_part(row.middle_name),
        normalize_identity_part(row.last_name),
        normalize_identity_part(row.suffix),
        row.party_candidate,
        row.filing_date.isoformat() if row.filing_date else "",
    )


def _build_candidates(
    eligible_rows: list[NcCandidateRow],
    row_contests: dict[int, str],
) -> tuple[CandidateFilingRecord, ...]:
    groups: dict[tuple[str, ...], list[NcCandidateRow]] = defaultdict(list)
    for row in eligible_rows:
        groups[_candidate_group_key(row, row_contests[row.row_number])].append(row)

    source_key_occurrences: Counter[str] = Counter()
    candidates = []
    for group_key, group_rows in groups.items():
        ordered_rows = sorted(group_rows, key=lambda row: row.row_number)
        first = ordered_rows[0]
        contest_public_id = group_key[0]
        evidence = []
        for row in ordered_rows:
            base_key = _source_row_base_key(row)
            source_key_occurrences[base_key] += 1
            occurrence = source_key_occurrences[base_key]
            source_row_key = base_key if occurrence == 1 else f"{base_key}/{occurrence}"
            evidence.append(
                _source_evidence(
                    row,
                    contest_public_id=contest_public_id,
                    source_row_key=source_row_key,
                )
            )

        filing_key = stable_public_id("filing", *group_key)
        candidates.append(
            CandidateFilingRecord(
                filing_key=filing_key,
                contest_public_id=contest_public_id,
                ballot_name=first.name_on_ballot,
                source_records=tuple(evidence),
                canonical_name=_reported_name(first),
                given_name=first.first_name,
                middle_name=first.middle_name,
                family_name=first.last_name,
                suffix=first.suffix,
                party_candidate=first.party_candidate,
                filing_date=first.filing_date,
                status="active",
            )
        )
    return tuple(sorted(candidates, key=lambda candidate: candidate.filing_key))


def build_pre_election_batch(
    rows: tuple[NcCandidateRow, ...],
    *,
    discovered_elections: tuple[ElectionRecord, ...] = (),
) -> PreElectionBatch:
    discovered_by_date: dict[date, list[ElectionRecord]] = defaultdict(list)
    elections: dict[str, ElectionRecord] = {}
    for election in discovered_elections:
        discovered_by_date[election.election_date].append(election)
        _put_unique(elections, election, label="election")

    measure_groups: dict[tuple[date, str, str], list[NcCandidateRow]] = defaultdict(list)
    eligible_by_date: dict[date, list[NcCandidateRow]] = defaultdict(list)
    for row in rows:
        if is_measure_contest(row.contest_name):
            measure_groups[(row.election_date, normalize_identity_part(row.contest_name), row.party_contest)].append(row)
        else:
            eligible_by_date[row.election_date].append(row)

    notices = [_measure_notice(group_rows) for group_rows in measure_groups.values()]
    row_elections: dict[int, ElectionRecord] = {}
    for election_date, date_rows in eligible_by_date.items():
        election, csv_only = _select_election(rows=date_rows, discovered_by_date=discovered_by_date)
        _put_unique(elections, election, label="election")
        if csv_only:
            notices.append(
                IngestionNotice(
                    code="csv_only_election",
                    subject_type="election",
                    subject_public_id=election.public_id,
                )
            )
        for row in date_rows:
            row_elections[row.row_number] = election

    jurisdictions: dict[str, JurisdictionRecord] = {}
    offices: dict[str, OfficeRecord] = {}
    contest_groups: dict[str, list[NcCandidateRow]] = defaultdict(list)
    contest_context: dict[str, tuple[ElectionRecord, OfficeRecord]] = {}
    row_contests: dict[int, str] = {}
    eligible_rows = [row for date_rows in eligible_by_date.values() for row in date_rows]
    for row in eligible_rows:
        mapped_jurisdictions = map_jurisdiction(row.contest_name, row.county_name)
        for jurisdiction in mapped_jurisdictions:
            _put_unique(jurisdictions, jurisdiction, label="jurisdiction")
        jurisdiction = mapped_jurisdictions[-1]
        office = map_office(
            row.contest_name,
            jurisdiction,
            term_years=row.term_years,
            vote_for=row.vote_for,
        )
        _put_unique(offices, office, label="office")
        election = row_elections[row.row_number]
        contest_public_id = _contest_key(row, election=election, office=office)
        contest_groups[contest_public_id].append(row)
        contest_context[contest_public_id] = (election, office)
        row_contests[row.row_number] = contest_public_id

    contests = []
    for contest_public_id, group_rows in contest_groups.items():
        first = group_rows[0]
        for field in ("vote_for", "is_partisan", "term_years"):
            if any(getattr(row, field) != getattr(first, field) for row in group_rows[1:]):
                raise ContractValidationError(f"normalized contest has conflicting {field}")
        election, office = contest_context[contest_public_id]
        contests.append(
            ContestRecord(
                public_id=contest_public_id,
                election_public_id=election.public_id,
                office_public_id=office.public_id,
                party_contest=first.party_contest,
                vote_for=first.vote_for,
                is_partisan=first.is_partisan,
                is_unexpired=first.is_unexpired,
                lifecycle_status="upcoming" if election.lifecycle_status == "upcoming" else "provisional",
                result_status="pending",
                source_key=(
                    f"{first.election_date.isoformat()}|{first.contest_name}|"
                    f"{first.party_contest or 'ALL'}|unexpired={str(first.is_unexpired).lower()}"
                ),
            )
        )

    candidates = _build_candidates(eligible_rows, row_contests)
    batch = PreElectionBatch(
        state="NC",
        jurisdictions=tuple(sorted(jurisdictions.values(), key=lambda record: record.public_id)),
        offices=tuple(sorted(offices.values(), key=lambda record: record.public_id)),
        elections=tuple(sorted(elections.values(), key=lambda record: record.public_id)),
        contests=tuple(sorted(contests, key=lambda record: record.public_id)),
        candidates=candidates,
        notices=tuple(sorted(notices, key=lambda notice: (notice.code, notice.subject_public_id))),
    )
    validate_pre_election_batch(batch)
    return batch
