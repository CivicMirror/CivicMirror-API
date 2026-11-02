from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcpfDistrict:
    district_code: int
    office_type: str
    district_description: str


@dataclass(frozen=True, slots=True)
class OcpfCandidateRow:
    cpf_id: int
    first_name: str
    last_name: str
    street_address: str
    city: str
    state: str
    zip_code: str
    district_code_sought: int | None
    office_type_sought: str
    district_name_sought: str
    closed_date: str
    party_affiliation: str


@dataclass(frozen=True, slots=True)
class SecretaryCandidateRow:
    office_label: str
    district_label: str | None
    party: str
    raw_line: str
    reported_name: str
    given_name: str
    middle_name: str
    family_name: str
    suffix: str
    address: str


@dataclass(frozen=True, slots=True)
class SecretaryPageParseResult:
    candidates: tuple[SecretaryCandidateRow, ...]
    no_nominations: tuple[tuple[str, str | None], ...]
