import io
import zipfile
from datetime import date, datetime

from cm2_ingestion.contracts import ContractValidationError
from cm2_nc.constants import S3_BASE_URL
from cm2_nc.source_records import NcResultRow

from .http import NcPublicBytesSource

REQUIRED_COLUMNS = (
    "County",
    "Election Date",
    "Precinct",
    "Contest Type",
    "Contest Name",
    "Choice",
    "Choice Party",
    "Vote For",
    "Total Votes",
    "Real Precinct",
)
_NO_DATA_PLACEHOLDER = "Data Unavailable"


def results_zip_url(election_date: date) -> str:
    compact = election_date.strftime("%Y%m%d")
    folder = election_date.strftime("%Y_%m_%d")
    return f"{S3_BASE_URL}/ENRS/{folder}/results_pct_{compact}.zip"


def _is_no_data_placeholder(archive: zipfile.ZipFile) -> bool:
    if archive.namelist() != ["Readme.txt"]:
        return False
    with archive.open("Readme.txt") as handle:
        return handle.read().decode("latin-1").strip() == _NO_DATA_PLACEHOLDER


def _parse_election_date(raw: str, *, row_number: int) -> date:
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date()
    except ValueError as exc:
        raise ContractValidationError(f"results row {row_number} has an invalid Election Date") from exc


def _parse_int(raw: str, *, row_number: int, field: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ContractValidationError(f"results row {row_number} field {field} is invalid") from exc


def parse_results_rows(zip_bytes: bytes) -> tuple[NcResultRow, ...]:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    if _is_no_data_placeholder(archive):
        return ()

    txt_names = [name for name in archive.namelist() if name.endswith(".txt")]
    if not txt_names:
        raise ContractValidationError("results ZIP has no .txt entry")

    with archive.open(txt_names[0]) as handle:
        lines = handle.read().decode("latin-1").splitlines()
    if not lines:
        return ()

    headers = [header.strip() for header in lines[0].split("\t")]
    if any(column not in headers for column in REQUIRED_COLUMNS):
        raise ContractValidationError("results TSV is missing required columns")
    index = {column: headers.index(column) for column in headers}

    rows = []
    for row_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < len(headers):
            parts += [""] * (len(headers) - len(parts))

        def field(name: str) -> str:
            return parts[index[name]].strip()

        contest_name = field("Contest Name")
        choice = field("Choice")
        if not contest_name or not choice:
            continue

        rows.append(
            NcResultRow(
                row_number=row_number,
                county_name=field("County"),
                election_date=_parse_election_date(field("Election Date"), row_number=row_number),
                precinct=field("Precinct"),
                contest_type=field("Contest Type"),
                contest_name=contest_name,
                choice=choice,
                choice_party=field("Choice Party"),
                vote_for=_parse_int(field("Vote For"), row_number=row_number, field="Vote For"),
                total_votes=_parse_int(field("Total Votes"), row_number=row_number, field="Total Votes"),
                is_real_precinct=field("Real Precinct").upper() == "Y",
            )
        )
    return tuple(rows)


class NcResultsZipSource(NcPublicBytesSource):
    def __init__(self, *, election_date: date, session=None):
        super().__init__(session=session)
        self.election_date = election_date
        self.url = results_zip_url(election_date)

    def parse(self, content: bytes, *, existing_elections=()):
        from cm2_nc.mapping.results import build_post_election_batch

        return build_post_election_batch(
            parse_results_rows(content),
            existing_elections=existing_elections,
        )
