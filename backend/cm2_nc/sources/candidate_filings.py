import csv
import io
from datetime import date, datetime

from cm2_ingestion.contracts import ContractValidationError, ElectionRecord, PreElectionBatch
from cm2_nc.constants import CANDIDATE_LIST_URL
from cm2_nc.source_records import NcCandidateRow

from .http import NcPublicBytesSource

REQUIRED_COLUMNS = (
    "election_dt",
    "county_name",
    "contest_name",
    "name_on_ballot",
    "first_name",
    "middle_name",
    "last_name",
    "name_suffix_lbl",
    "nick_name",
    "street_address",
    "city",
    "state",
    "zip_code",
    "phone",
    "office_phone",
    "business_phone",
    "email",
    "candidacy_dt",
    "party_contest",
    "party_candidate",
    "is_unexpired",
    "has_primary",
    "is_partisan",
    "vote_for",
    "term",
)


def _structural_error(row_number: int, field: str) -> ContractValidationError:
    return ContractValidationError(f"candidate CSV row {row_number} field {field} is invalid")


def _parse_date(raw: str, *, row_number: int, field: str, required: bool) -> date | None:
    value = raw.strip()
    if not value and not required:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError as exc:
        raise _structural_error(row_number, field) from exc


def _parse_bool(raw: str, *, row_number: int, field: str) -> bool:
    value = raw.strip().upper()
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    raise _structural_error(row_number, field)


def _parse_positive_int(raw: str, *, row_number: int, field: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise _structural_error(row_number, field) from exc
    if value <= 0:
        raise _structural_error(row_number, field)
    return value


def _protected_address(row: dict[str, str]) -> str:
    city = row["city"].strip()
    state_zip = " ".join(part for part in (row["state"].strip(), row["zip_code"].strip()) if part)
    return ", ".join(part for part in (row["street_address"].strip(), city, state_zip) if part)


def _protected_phone(row: dict[str, str]) -> str:
    values = []
    for field in ("phone", "office_phone", "business_phone"):
        value = row[field].strip()
        if value and value not in values:
            values.append(value)
    return "; ".join(values)


def parse_candidate_rows(content: bytes) -> tuple[NcCandidateRow, ...]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = tuple(reader.fieldnames or ())
    if any(column not in headers for column in REQUIRED_COLUMNS):
        raise ContractValidationError("candidate CSV is missing required columns")

    records = []
    for row_number, raw_row in enumerate(reader, start=2):
        row = {column: (raw_row.get(column) or "") for column in REQUIRED_COLUMNS}
        contest_name = row["contest_name"].strip()
        ballot_name = row["name_on_ballot"].strip()
        if not contest_name:
            raise _structural_error(row_number, "contest_name")
        if not ballot_name:
            raise _structural_error(row_number, "name_on_ballot")
        records.append(
            NcCandidateRow(
                row_number=row_number,
                election_date=_parse_date(
                    row["election_dt"],
                    row_number=row_number,
                    field="election_dt",
                    required=True,
                ),
                county_name=row["county_name"].strip(),
                contest_name=contest_name,
                name_on_ballot=ballot_name,
                first_name=row["first_name"].strip(),
                middle_name=row["middle_name"].strip(),
                last_name=row["last_name"].strip(),
                suffix=row["name_suffix_lbl"].strip(),
                nickname=row["nick_name"].strip(),
                protected_address=_protected_address(row),
                protected_phone=_protected_phone(row),
                protected_email=row["email"].strip(),
                filing_date=_parse_date(
                    row["candidacy_dt"],
                    row_number=row_number,
                    field="candidacy_dt",
                    required=False,
                ),
                party_contest=row["party_contest"].strip().upper(),
                party_candidate=row["party_candidate"].strip().upper(),
                is_unexpired=_parse_bool(
                    row["is_unexpired"],
                    row_number=row_number,
                    field="is_unexpired",
                ),
                has_primary=_parse_bool(
                    row["has_primary"],
                    row_number=row_number,
                    field="has_primary",
                ),
                is_partisan=_parse_bool(
                    row["is_partisan"],
                    row_number=row_number,
                    field="is_partisan",
                ),
                vote_for=_parse_positive_int(row["vote_for"], row_number=row_number, field="vote_for"),
                term_years=_parse_positive_int(row["term"], row_number=row_number, field="term"),
            )
        )
    return tuple(records)


class NcCandidateRowsSource(NcPublicBytesSource):
    url = CANDIDATE_LIST_URL

    def parse(self, content: bytes) -> tuple[NcCandidateRow, ...]:
        return parse_candidate_rows(content)


class NcCandidateFilingsSource(NcCandidateRowsSource):
    def parse(
        self,
        content: bytes,
        *,
        discovered_elections: tuple[ElectionRecord, ...] = (),
    ) -> PreElectionBatch:
        from cm2_nc.mapping.batch import build_pre_election_batch

        return build_pre_election_batch(
            parse_candidate_rows(content),
            discovered_elections=discovered_elections,
        )
