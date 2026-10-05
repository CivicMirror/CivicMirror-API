import re

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
from cm2_ma.mapping.identity import contest_public_id, stable_public_id
from cm2_ma.mapping.jurisdictions import map_jurisdiction
from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.mapping.office_crosswalk import resolve_district_code
from cm2_ma.mapping.offices import map_office
from cm2_ma.source_records import SecretaryCandidateRow

# Same vacancy-qualifier pattern used by office_crosswalk._office_key /
# offices._office_key / jurisdictions._office_key: an office_label like
# "Sheriff (to fill a vacancy)" carries a parenthetical qualifier that those
# modules strip before lookup. Here we need the *opposite* signal: whether the
# qualifier was present at all, since contest identity includes is_unexpired.
_VACANCY_QUALIFIER_RE = re.compile(r"\s*\(.*\)\s*$")


def _is_unexpired_term(office_label: str) -> bool:
    return _VACANCY_QUALIFIER_RE.sub("", office_label).strip() != office_label.strip()


def _select_primary_election(discovered_elections: tuple[ElectionRecord, ...]) -> ElectionRecord:
    primaries = [election for election in discovered_elections if election.election_type == "primary"]
    if len(primaries) != 1:
        raise ContractValidationError(
            f"expected exactly one discovered primary election, found {len(primaries)}"
        )
    return primaries[0]


def _put_unique(records: dict[str, object], record, *, label: str) -> None:
    existing = records.get(record.public_id)
    if existing is not None and existing != record:
        raise ContractValidationError(f"conflicting normalized {label} mapping")
    records[record.public_id] = record


def _resolve_person_public_id(
    row: SecretaryCandidateRow, *, ocpf_pool: OcpfCandidatePool
) -> str | None:
    district_code = resolve_district_code(
        office_label=row.office_label, district_label=row.district_label, districts=ocpf_pool.districts
    )
    if district_code is None:
        return None
    full_name = " ".join(part for part in (row.given_name, row.family_name) if part)
    match = ocpf_pool.find_by_name_and_district_code(full_name=full_name, district_code=district_code)
    if match is None:
        return None
    if match.party_affiliation.casefold() != row.party.casefold():
        # A wrong crosswalk assumption should mean no match, never a wrong
        # match: a same-name, same-district, opposite-party OCPF filer is not
        # the same person as this Secretary-page row.
        return None
    return stable_public_id("person", "ocpf", str(match.cpf_id))


def _no_nomination_notice(office_label: str, district_label: str | None) -> IngestionNotice:
    identity = stable_public_id("source-contest", office_label, district_label or "")
    return IngestionNotice(
        code="no_nominations", subject_type="office_district", subject_public_id=identity
    )


def build_pre_election_batch(
    rows: tuple[SecretaryCandidateRow, ...],
    *,
    no_nominations: tuple[tuple[str, str | None], ...],
    discovered_elections: tuple[ElectionRecord, ...],
    ocpf_pool: OcpfCandidatePool,
) -> PreElectionBatch:
    election = _select_primary_election(discovered_elections)

    jurisdictions: dict[str, JurisdictionRecord] = {}
    offices: dict[str, OfficeRecord] = {}
    contests: dict[str, ContestRecord] = {}
    candidates: list[CandidateFilingRecord] = []

    for row in rows:
        mapped_jurisdictions = map_jurisdiction(row.office_label, row.district_label)
        for jurisdiction in mapped_jurisdictions:
            _put_unique(jurisdictions, jurisdiction, label="jurisdiction")
        jurisdiction = mapped_jurisdictions[-1]

        office = map_office(row.office_label, jurisdiction)
        _put_unique(offices, office, label="office")

        is_unexpired = _is_unexpired_term(row.office_label)
        contest_id = contest_public_id(
            election_public_id=election.public_id,
            office_public_id=office.public_id,
            party_contest=row.party,
            is_unexpired=is_unexpired,
        )
        if contest_id not in contests:
            contests[contest_id] = ContestRecord(
                public_id=contest_id,
                election_public_id=election.public_id,
                office_public_id=office.public_id,
                party_contest=row.party,
                vote_for=1,
                is_partisan=True,
                is_unexpired=is_unexpired,
                lifecycle_status="upcoming",
                result_status="pending",
                source_key=f"{row.office_label}|{row.district_label or ''}|{row.party}",
            )

        source_row_key = stable_public_id(
            "source-row", contest_id, row.party, row.raw_line
        )
        evidence = PersonSourceEvidence(
            source_row_key=source_row_key,
            reported_name=row.reported_name,
            ballot_name=row.reported_name,
            given_name=row.given_name,
            middle_name=row.middle_name,
            family_name=row.family_name,
            suffix=row.suffix,
            filing_data={
                "office_label": row.office_label,
                "district_label": row.district_label or "",
                "raw_line": row.raw_line,
            },
            protected_address=row.address,
            retrieval_context={"party": row.party},
        )

        candidates.append(
            CandidateFilingRecord(
                filing_key=stable_public_id("filing", contest_id, source_row_key),
                contest_public_id=contest_id,
                ballot_name=row.reported_name,
                source_records=(evidence,),
                person_public_id=_resolve_person_public_id(row, ocpf_pool=ocpf_pool),
                canonical_name=row.reported_name,
                given_name=row.given_name,
                middle_name=row.middle_name,
                family_name=row.family_name,
                suffix=row.suffix,
                party_candidate=row.party,
                status="active",
            )
        )

    notices = tuple(
        _no_nomination_notice(office_label, district_label)
        for office_label, district_label in no_nominations
    )

    batch = PreElectionBatch(
        state="MA",
        jurisdictions=tuple(sorted(jurisdictions.values(), key=lambda record: record.public_id)),
        offices=tuple(sorted(offices.values(), key=lambda record: record.public_id)),
        elections=(election,),
        contests=tuple(sorted(contests.values(), key=lambda record: record.public_id)),
        candidates=tuple(candidates),
        notices=notices,
    )
    validate_pre_election_batch(batch)
    return batch
