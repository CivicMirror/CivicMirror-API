import hashlib
import re
from collections import defaultdict
from datetime import date

from cm2_ingestion.contracts import (
    ContestRecord,
    ContractValidationError,
    ElectionRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PostElectionBatch,
    PrecinctResultObservation,
    validate_post_election_batch,
)
from cm2_nc.source_records import NcResultRow

from .identity import contest_public_id, normalize_identity_part, stable_public_id
from .jurisdictions import map_jurisdiction
from .measures import is_measure_contest
from .offices import map_office

_PARTY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,5})\)$")
_UNEXPIRED_SUFFIX_RE = re.compile(r"\s*\(UNEXPIRED\)$")
_WRITE_IN_MARKER_RE = re.compile(r"\(\s*WRITE-IN\s*\)|\bWRITE-IN\b|\(\s*MISCELLANEOUS\s*\)", re.IGNORECASE)


def split_contest_label(raw_label: str) -> tuple[str, str, bool]:
    label = " ".join((raw_label or "").strip().upper().split())

    party = ""
    party_match = _PARTY_SUFFIX_RE.search(label)
    if party_match:
        party = party_match.group(1)
        label = label[: party_match.start()].strip()

    is_unexpired = False
    if _UNEXPIRED_SUFFIX_RE.search(label):
        is_unexpired = True
        label = _UNEXPIRED_SUFFIX_RE.sub("", label).strip()

    return label, party, is_unexpired


def classify_choice(source_label: str) -> str:
    if not _WRITE_IN_MARKER_RE.search(source_label or ""):
        return "candidate"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label).strip()
    if normalize_identity_part(remainder) in {"", "miscellaneous"}:
        return "write_in_aggregate"
    return "named_write_in"


def normalized_choice_label(source_label: str, choice_type: str) -> str:
    if choice_type == "write_in_aggregate":
        return "write-in"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label or "").strip()
    return normalize_identity_part(remainder)


def _put_unique(records: dict[str, object], record, *, label: str) -> None:
    existing = records.get(record.public_id)
    if existing is not None and existing != record:
        raise ContractValidationError(f"conflicting normalized {label} mapping")
    records[record.public_id] = record


def _select_election(
    *,
    election_date: date,
    has_party_signal: bool,
    existing_elections: tuple[ElectionRecord, ...],
) -> ElectionRecord:
    candidates = [record for record in existing_elections if record.election_date == election_date]
    if not candidates:
        raise ContractValidationError("results file references an unknown election date")
    if len(candidates) == 1:
        return candidates[0]

    preferred_type = "primary" if has_party_signal else "general"
    preferred = [record for record in candidates if record.election_type == preferred_type]
    if len(preferred) == 1:
        return preferred[0]
    raise ContractValidationError("results file date matches multiple elections ambiguously")


def _measure_notice(row: NcResultRow, base_name: str, party: str) -> IngestionNotice:
    identity = "\x1f".join((row.election_date.isoformat(), normalize_identity_part(base_name), party))
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return IngestionNotice(
        code="measure_excluded",
        subject_type="source_contest",
        subject_public_id=f"nc/source-contest/{digest}",
    )


def build_post_election_batch(
    rows: tuple[NcResultRow, ...],
    *,
    existing_elections: tuple[ElectionRecord, ...] = (),
) -> PostElectionBatch:
    split_by_row: dict[int, tuple[str, str, bool]] = {
        row.row_number: split_contest_label(row.contest_name) for row in rows
    }

    eligible_rows: list[NcResultRow] = []
    notices: list[IngestionNotice] = []
    seen_measures: set[tuple[date, str, str]] = set()
    for row in rows:
        base_name, party, _ = split_by_row[row.row_number]
        if is_measure_contest(base_name):
            measure_key = (row.election_date, normalize_identity_part(base_name), party)
            if measure_key not in seen_measures:
                seen_measures.add(measure_key)
                notices.append(_measure_notice(row, base_name, party))
            continue
        eligible_rows.append(row)

    party_signal_by_date: dict[date, bool] = defaultdict(bool)
    for row in eligible_rows:
        _, party, _ = split_by_row[row.row_number]
        if party:
            party_signal_by_date[row.election_date] = True

    election_by_date: dict[date, ElectionRecord] = {}
    for row in eligible_rows:
        if row.election_date not in election_by_date:
            election_by_date[row.election_date] = _select_election(
                election_date=row.election_date,
                has_party_signal=party_signal_by_date[row.election_date],
                existing_elections=existing_elections,
            )

    jurisdictions: dict[str, JurisdictionRecord] = {}
    offices: dict[str, OfficeRecord] = {}
    contests: dict[str, ContestRecord] = {}
    row_contest_id: dict[int, str] = {}

    for row in eligible_rows:
        base_name, party, is_unexpired = split_by_row[row.row_number]
        mapped_jurisdictions = map_jurisdiction(base_name, row.county_name)
        for jurisdiction in mapped_jurisdictions:
            _put_unique(jurisdictions, jurisdiction, label="jurisdiction")
        jurisdiction = mapped_jurisdictions[-1]
        office = map_office(base_name, jurisdiction, vote_for=row.vote_for)
        _put_unique(offices, office, label="office")

        election = election_by_date[row.election_date]
        contest_id = contest_public_id(
            election_public_id=election.public_id,
            office_public_id=office.public_id,
            party_contest=party,
            is_unexpired=is_unexpired,
        )
        if contest_id not in contests:
            contests[contest_id] = ContestRecord(
                public_id=contest_id,
                election_public_id=election.public_id,
                office_public_id=office.public_id,
                party_contest=party,
                vote_for=row.vote_for,
                is_partisan=bool(party),
                is_unexpired=is_unexpired,
                lifecycle_status="active",
                result_status="unofficial",
                source_key=f"{row.election_date.isoformat()}|{base_name}|{party or 'ALL'}|unexpired={str(is_unexpired).lower()}",
            )
        row_contest_id[row.row_number] = contest_id

    observations = []
    for row in eligible_rows:
        contest_id = row_contest_id[row.row_number]
        choice_type = classify_choice(row.choice)
        normalized_label = normalized_choice_label(row.choice, choice_type)
        source_choice_key = stable_public_id("result-choice", contest_id, choice_type, normalized_label)
        observation_key = stable_public_id(
            "result-observation",
            contest_id,
            choice_type,
            row.county_name,
            row.precinct,
            normalized_label,
        )
        observations.append(
            PrecinctResultObservation(
                source_observation_key=observation_key,
                contest_public_id=contest_id,
                source_choice_key=source_choice_key,
                source_label=row.choice,
                normalized_label=normalized_label,
                choice_type=choice_type,
                choice_party=row.choice_party,
                vote_total=row.total_votes,
                precinct=row.precinct,
            )
        )

    batch = PostElectionBatch(
        state="NC",
        new_jurisdictions=tuple(sorted(jurisdictions.values(), key=lambda record: record.public_id)),
        new_offices=tuple(sorted(offices.values(), key=lambda record: record.public_id)),
        new_contests=tuple(sorted(contests.values(), key=lambda record: record.public_id)),
        observations=tuple(observations),
        notices=tuple(sorted(notices, key=lambda notice: notice.subject_public_id)),
    )
    validate_post_election_batch(batch)
    return batch
