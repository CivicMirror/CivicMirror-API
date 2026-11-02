# CM2 MA Pilot — Plan 2: OCPF Identity Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse OCPF's district-code reference table and candidate-filer bulk data into typed records, and build an in-memory matching pool (`OcpfCandidatePool`) that a later plan can query by `(full_name, district_code)` to pre-resolve candidate identity before falling back to fuzzy/provisional matching.

**Architecture:** Two new plain-HTTP sources (`sources/ocpf_districts.py`, `sources/ocpf_filers.py`) — unlike Plan 1's Secretary-page sources, OCPF's `ocpf2.blob.core.windows.net` bulk files are NOT behind Incapsula, so these use a new `MaPublicBytesSource` base class (plain `requests.get()`, mirroring `cm2_nc.sources.http.NcPublicBytesSource`) rather than the solver. Both sources return a ZIP; the district source unzips a tab-delimited `.txt`, the filer source unzips an `.xlsx` and reads its `"All Candidates"` sheet. A third module, `mapping/ocpf_pool.py`, combines both into `OcpfCandidatePool` — closed-date-filtered, indexed for lookup. This plan does not touch the Secretary pages, election discovery (Plan 1, already complete), or any DB persistence — `OcpfCandidatePool` is a pure in-memory matching aid, per the design spec's explicit call that OCPF data is never persisted through its own contract path.

**Tech Stack:** Django 5 / Python 3.13, `openpyxl` (already a project dependency — used today by `al_sos`, `oh` results adapter, etc.), `requests`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md` (see "Offices, jurisdictions, and candidate identity — OCPF" and "Candidate identity: OCPF as source, Secretary as confirmation" sections)

## Global Constraints

- Python 3.13 runtime only (project requires `>=3.13,<3.14`).
- `core/cf_solver.py` must not be modified or used by this plan — OCPF's bulk files are NOT Incapsula-blocked (verified live 2026-08-17 with plain `curl`), so nothing in this plan touches the solver.
- Follow the existing `cm2_nc` app's structure and naming conventions exactly (one source module per distinct source, `source_records.py` for raw-row dataclasses, in-memory test fixtures built via helper functions rather than committed binary files — see `cm2_nc/tests/test_sources.py`'s `_zip_bytes()` helper, which this plan's tests extend the same pattern for `.xlsx`-in-`.zip`).
- `cm2_ingestion.contracts` is shared and must not be modified by this plan.
- `OcpfCandidatePool` never creates `Person`/`Candidacy`/any DB row — it is a pure in-memory data structure for a later plan to query. Do not add persistence in this plan.
- All new tests must run under `pytest --no-migrations` (per project convention), executed via `docker compose -f docker-compose.v2.yaml run --rm test pytest ...` — NOT the host's bare Python (host is 3.14, project requires 3.13).
- `ruff check backend/cm2_ma` must stay clean (matches Plan 1's Definition of Done and the whole-branch review finding that made this explicit).

---

## File Structure

```
backend/cm2_ma/
  constants.py                     # MODIFY: add OCPF URLs + parser versions
  source_records.py                # NEW: OcpfDistrict, OcpfCandidateRow dataclasses
  sources/
    http.py                        # NEW: MaPublicBytesSource (plain HTTP, mirrors NcPublicBytesSource)
    ocpf_districts.py              # NEW: district-code table parser + source class
    ocpf_filers.py                 # NEW: candidate-filer xlsx parser + source class
  mapping/
    __init__.py                    # NEW
    ocpf_pool.py                   # NEW: OcpfCandidatePool (closed-date filter + name/district-code matching)
  tests/
    test_ocpf_districts.py         # NEW
    test_ocpf_filers.py            # NEW
    test_ocpf_pool.py              # NEW
```

No fixture files are committed as binary artifacts — tests build ZIP/XLSX bytes in-memory using helper functions, following the `_zip_bytes()` pattern already established in `cm2_nc/tests/test_sources.py`.

---

### Task 1: Plain-HTTP source base + district-code table parser

**Files:**
- Modify: `backend/cm2_ma/constants.py`
- Create: `backend/cm2_ma/source_records.py`
- Create: `backend/cm2_ma/sources/http.py`
- Create: `backend/cm2_ma/sources/ocpf_districts.py`
- Test: `backend/cm2_ma/tests/test_ocpf_districts.py`

**Interfaces:**
- Consumes: `cm2_ingestion.contracts.ContractValidationError` (existing, shared).
- Produces: `cm2_ma.sources.http.MaPublicBytesSource` (base class: `source_system`, `url: str = ""`, `__init__(self, *, session=None)`, `acquire(self) -> bytes`) — consumed by Task 2. `cm2_ma.source_records.OcpfDistrict` (fields: `district_code: int`, `office_type: str`, `district_description: str`) — consumed by Task 3. `cm2_ma.sources.ocpf_districts.parse_district_codes(zip_bytes: bytes) -> tuple[OcpfDistrict, ...]` and `OcpfDistrictCodeListSource(MaPublicBytesSource)` — consumed by Task 3.

This task is grounded in the real file, fetched and inspected live during design: `https://ocpf2.blob.core.windows.net/downloads/data2/district_code_list.zip` contains a tab-delimited `district_code_list.txt` (714 lines including header, CRLF line endings, ASCII encoding). Header row is exactly `District_Code\tOffice_Type_Description\tDistrict_Description`. A handful of `District_Description` values are wrapped in literal double-quotes because they contain a comma (confirmed live: `125\tSenate\t"Norfolk, Bristol & Plymouth"\r\n`) — the parser must strip a wrapping quote pair when present.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_ocpf_districts.py`:
```python
import io
import zipfile

import pytest

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_DISTRICT_CODE_LIST_URL
from cm2_ma.sources.ocpf_districts import OcpfDistrictCodeListSource, parse_district_codes


def _district_zip_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("district_code_list.txt", text)
    return buffer.getvalue()


# Real header + real sample rows captured live from the source, including the
# CRLF line endings and the literal double-quote wrapping a comma-containing
# description that the live file actually uses.
_SAMPLE_TEXT = (
    "District_Code\tOffice_Type_Description\tDistrict_Description\r\n"
    "104\tSenate\t1st Plymouth & Bristol\r\n"
    "125\tSenate\t\"Norfolk, Bristol & Plymouth\"\r\n"
    "231\tHouse\t9th Essex\r\n"
    "1114\tStatewide\tAuditor\r\n"
)


def test_parses_rows_and_strips_quoted_comma_descriptions():
    districts = parse_district_codes(_district_zip_bytes(_SAMPLE_TEXT))

    assert len(districts) == 4
    by_code = {district.district_code: district for district in districts}
    assert by_code[104].office_type == "Senate"
    assert by_code[104].district_description == "1st Plymouth & Bristol"
    assert by_code[125].district_description == "Norfolk, Bristol & Plymouth"
    assert by_code[231] .office_type == "House"
    assert by_code[1114].office_type == "Statewide"
    assert by_code[1114].district_description == "Auditor"


def test_rejects_missing_header_columns():
    bad_text = "Code\tType\tDescription\r\n104\tSenate\t1st Plymouth & Bristol\r\n"

    with pytest.raises(ContractValidationError, match="missing required columns"):
        parse_district_codes(_district_zip_bytes(bad_text))


def test_rejects_zip_with_no_txt_entry():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("district_code_list.xlsx", b"not actually an xlsx")

    with pytest.raises(ContractValidationError, match="no .txt entry"):
        parse_district_codes(buffer.getvalue())


def test_skips_blank_trailing_lines():
    text = _SAMPLE_TEXT + "\r\n"
    districts = parse_district_codes(_district_zip_bytes(text))
    assert len(districts) == 4


def test_source_url_and_parse_delegate_correctly():
    source = OcpfDistrictCodeListSource()
    assert source.url == OCPF_DISTRICT_CODE_LIST_URL

    districts = source.parse(_district_zip_bytes(_SAMPLE_TEXT))
    assert len(districts) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run (from the repo root): `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_districts.py -v --no-migrations`

Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources.ocpf_districts'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/cm2_ma/constants.py` (append; do not remove existing content):
```python
OCPF_DISTRICT_CODE_LIST_URL = (
    "https://ocpf2.blob.core.windows.net/downloads/data2/district_code_list.zip"
)
OCPF_FILERS_URL = "https://ocpf2.blob.core.windows.net/downloads/data2/ocpf-filers-excel.zip"
OCPF_DISTRICT_PARSER_VERSION = "ma-ocpf-district-v1"
OCPF_FILERS_PARSER_VERSION = "ma-ocpf-filers-v1"
```

`backend/cm2_ma/source_records.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcpfDistrict:
    district_code: int
    office_type: str
    district_description: str
```

`backend/cm2_ma/sources/http.py`:
```python
import requests

from cm2_ma.constants import SOURCE_SYSTEM, SOURCE_TIMEOUT_SECONDS


class MaPublicBytesSource:
    """
    Base class for cm2_ma sources that are plain, unauthenticated HTTP —
    unlike sec.state.ma.us (see sources/solver.py), OCPF's bulk data files
    (ocpf2.blob.core.windows.net) are not behind any bot protection, so a
    direct requests.get() works. Mirrors cm2_nc.sources.http.NcPublicBytesSource.
    """

    source_system = SOURCE_SYSTEM
    url = ""

    def __init__(self, *, session=None):
        self._session = session or requests.Session()

    def acquire(self) -> bytes:
        response = self._session.get(self.url, timeout=SOURCE_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content
```

`backend/cm2_ma/sources/ocpf_districts.py`:
```python
import io
import zipfile

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_DISTRICT_CODE_LIST_URL
from cm2_ma.source_records import OcpfDistrict

from .http import MaPublicBytesSource

REQUIRED_COLUMNS = ("District_Code", "Office_Type_Description", "District_Description")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_district_codes(zip_bytes: bytes) -> tuple[OcpfDistrict, ...]:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    txt_names = [name for name in archive.namelist() if name.endswith(".txt")]
    if not txt_names:
        raise ContractValidationError("district code ZIP has no .txt entry")

    with archive.open(txt_names[0]) as handle:
        lines = handle.read().decode("ascii", errors="replace").splitlines()
    if not lines:
        return ()

    headers = lines[0].split("\t")
    if list(headers) != list(REQUIRED_COLUMNS):
        raise ContractValidationError("district code file is missing required columns")

    districts = []
    for row_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != len(headers):
            raise ContractValidationError(f"district code row {row_number} has the wrong column count")
        code_text, office_type, district_description = parts
        try:
            district_code = int(code_text.strip())
        except ValueError as exc:
            raise ContractValidationError(
                f"district code row {row_number} has an invalid District_Code"
            ) from exc
        districts.append(
            OcpfDistrict(
                district_code=district_code,
                office_type=office_type.strip(),
                district_description=_strip_quotes(district_description.strip()),
            )
        )
    return tuple(districts)


class OcpfDistrictCodeListSource(MaPublicBytesSource):
    url = OCPF_DISTRICT_CODE_LIST_URL

    def parse(self, content: bytes) -> tuple[OcpfDistrict, ...]:
        return parse_district_codes(content)
```

Also create `backend/cm2_ma/sources/__init__.py` if it does not already exist (it should already exist from Plan 1 — do not overwrite it if present).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_districts.py -v --no-migrations`
Expected: PASS (5 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean (no new errors)

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/constants.py backend/cm2_ma/source_records.py backend/cm2_ma/sources/http.py backend/cm2_ma/sources/ocpf_districts.py backend/cm2_ma/tests/test_ocpf_districts.py
git commit -m "feat(cm2_ma): parse OCPF district-code reference table"
```

---

### Task 2: Candidate-filer bulk data parser

**Files:**
- Modify: `backend/cm2_ma/source_records.py`
- Create: `backend/cm2_ma/sources/ocpf_filers.py`
- Test: `backend/cm2_ma/tests/test_ocpf_filers.py`

**Interfaces:**
- Consumes: `cm2_ma.sources.http.MaPublicBytesSource` (Task 1), `cm2_ma.constants.OCPF_FILERS_URL` (Task 1), `cm2_ingestion.contracts.ContractValidationError`.
- Produces: `cm2_ma.source_records.OcpfCandidateRow` (fields: `cpf_id: int`, `first_name: str`, `last_name: str`, `street_address: str`, `city: str`, `state: str`, `zip_code: str`, `district_code_sought: int | None`, `office_type_sought: str`, `district_name_sought: str`, `closed_date: str`, `party_affiliation: str`) — consumed by Task 3. `cm2_ma.sources.ocpf_filers.parse_candidate_filers(zip_bytes: bytes) -> tuple[OcpfCandidateRow, ...]` and `OcpfFilersSource(MaPublicBytesSource)` — consumed by Task 3.

Grounded in the real file, fetched and inspected live during design: `https://ocpf2.blob.core.windows.net/downloads/data2/ocpf-filers-excel.zip` contains a single `filer-spreadsheet.xlsx` with four sheets (`"All Filers"`, `"All Candidates"`, `"PACs"`, `"Local Party Committees"`); this parser reads only `"All Candidates"` (6,802 real rows as of 2026-08-17). Real header row (exact column names, verified via `openpyxl`):
`CPF ID, Account Type Code, Comm_Name, Is_Candidate_Only, Candidate First Name, Candidate Last Name, Candidate Street Address, Candidate City, Candidate State, Candidate Zip Code, Treasurer First Name, Treasurer Last Name, Comm Street Address, Comm City, Comm State, Comm Zip Code, Chair First Name, Chair Last Name, Organization Date, District Code Sought, Office Type Sought, District Name Sought, District Code Held, Office Type Held, District Name Held, Closed Date, Party Affiliation`.
A real sample row (values, in header order): `10010, 'U', 'Angelo Committee', 'False', 'Steven', 'Angelo', '39 Popmonet Rd', 'E. Falmouth', 'MA', '02536', 'Andrew', 'Angelo', '60 Halstead Street', 'Saugus', 'MA', '01906', '', '', '2/21/1980', 231, 'House', '9th Essex', 0, 'N/A', 'No office', '', 'Democratic'`. `Closed Date` is an empty string for open/active filers and a date string (e.g. `'7/12/2013'`) for closed ones — this parser stores it as-is; Task 3's pool does the active-filtering.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_ocpf_filers.py`:
```python
import io
import zipfile

import pytest
from openpyxl import Workbook

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_FILERS_URL
from cm2_ma.sources.ocpf_filers import OcpfFilersSource, parse_candidate_filers

# Real header, exact column order, captured live from the source workbook's
# "All Candidates" sheet.
_HEADER = (
    "CPF ID", "Account Type Code", "Comm_Name", "Is_Candidate_Only",
    "Candidate First Name", "Candidate Last Name", "Candidate Street Address",
    "Candidate City", "Candidate State", "Candidate Zip Code",
    "Treasurer First Name", "Treasurer Last Name", "Comm Street Address",
    "Comm City", "Comm State", "Comm Zip Code", "Chair First Name",
    "Chair Last Name", "Organization Date", "District Code Sought",
    "Office Type Sought", "District Name Sought", "District Code Held",
    "Office Type Held", "District Name Held", "Closed Date", "Party Affiliation",
)

# Two real sample rows: one open/active (no Closed Date), one closed.
_OPEN_ROW = (
    10010, "U", "Angelo Committee", "False", "Steven", "Angelo", "39 Popmonet Rd",
    "E. Falmouth", "MA", "02536", "Andrew", "Angelo", "60 Halstead Street",
    "Saugus", "MA", "01906", "", "", "2/21/1980", 231, "House", "9th Essex",
    0, "N/A", "No office", "", "Democratic",
)
_CLOSED_ROW = (
    10025, "U", "Berry Committee", "False", "Frederick E.", "Berry",
    "8 Crowninshield Street Unit 410", "Peabody", "MA", "01960",
    "Michael F.", "Tierney", "56 School Street", "Salem", "MA", "01970-2359",
    "", "", "2/5/1982", 107, "Senate", "2nd Essex", 0, "N/A", "No office",
    "7/12/2013", "Democratic",
)


def _filers_zip_bytes(rows: list[tuple]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in ("All Filers", "All Candidates", "PACs", "Local Party Committees"):
        sheet = workbook.create_sheet(sheet_name)
        if sheet_name == "All Candidates":
            sheet.append(_HEADER)
            for row in rows:
                sheet.append(row)
    xlsx_buffer = io.BytesIO()
    workbook.save(xlsx_buffer)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("filer-spreadsheet.xlsx", xlsx_buffer.getvalue())
    return zip_buffer.getvalue()


def test_parses_open_and_closed_rows():
    candidates = parse_candidate_filers(_filers_zip_bytes([_OPEN_ROW, _CLOSED_ROW]))

    assert len(candidates) == 2
    by_cpf_id = {candidate.cpf_id: candidate for candidate in candidates}

    steven = by_cpf_id[10010]
    assert steven.first_name == "Steven"
    assert steven.last_name == "Angelo"
    assert steven.district_code_sought == 231
    assert steven.office_type_sought == "House"
    assert steven.district_name_sought == "9th Essex"
    assert steven.closed_date == ""
    assert steven.party_affiliation == "Democratic"

    frederick = by_cpf_id[10025]
    assert frederick.closed_date == "7/12/2013"
    assert frederick.district_code_sought == 107


def test_rejects_workbook_without_all_candidates_sheet():
    workbook = Workbook()
    xlsx_buffer = io.BytesIO()
    workbook.save(xlsx_buffer)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("filer-spreadsheet.xlsx", xlsx_buffer.getvalue())

    with pytest.raises(ContractValidationError, match="All Candidates"):
        parse_candidate_filers(zip_buffer.getvalue())


def test_rejects_zip_with_no_xlsx_entry():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("readme.txt", "not a workbook")

    with pytest.raises(ContractValidationError, match="no .xlsx entry"):
        parse_candidate_filers(zip_buffer.getvalue())


def test_source_url_and_parse_delegate_correctly():
    source = OcpfFilersSource()
    assert source.url == OCPF_FILERS_URL

    candidates = source.parse(_filers_zip_bytes([_OPEN_ROW]))
    assert len(candidates) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_filers.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources.ocpf_filers'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/cm2_ma/source_records.py` (append after `OcpfDistrict`; do not remove it):
```python
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
```

`backend/cm2_ma/sources/ocpf_filers.py`:
```python
import io
import zipfile

from openpyxl import load_workbook

from cm2_ingestion.contracts import ContractValidationError
from cm2_ma.constants import OCPF_FILERS_URL
from cm2_ma.source_records import OcpfCandidateRow

from .http import MaPublicBytesSource

REQUIRED_COLUMNS = (
    "CPF ID", "Candidate First Name", "Candidate Last Name",
    "Candidate Street Address", "Candidate City", "Candidate State",
    "Candidate Zip Code", "District Code Sought", "Office Type Sought",
    "District Name Sought", "Closed Date", "Party Affiliation",
)


def _cell_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_candidate_filers(zip_bytes: bytes) -> tuple[OcpfCandidateRow, ...]:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    xlsx_names = [name for name in archive.namelist() if name.endswith(".xlsx")]
    if not xlsx_names:
        raise ContractValidationError("OCPF filers ZIP has no .xlsx entry")

    with archive.open(xlsx_names[0]) as handle:
        workbook = load_workbook(io.BytesIO(handle.read()), read_only=True, data_only=True)

    if "All Candidates" not in workbook.sheetnames:
        raise ContractValidationError("OCPF filer workbook has no 'All Candidates' sheet")
    sheet = workbook["All Candidates"]

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if header_row is None:
        return ()
    header = [str(cell).strip() if cell is not None else "" for cell in header_row]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ContractValidationError("OCPF 'All Candidates' sheet is missing required columns")
    index = {column: header.index(column) for column in header}

    candidates = []
    for row in rows_iter:
        def field(name: str):
            return row[index[name]]

        cpf_id_value = field("CPF ID")
        if cpf_id_value is None:
            continue
        district_code_value = field("District Code Sought")
        district_code_sought = (
            int(district_code_value) if district_code_value not in (None, "") else None
        )

        candidates.append(
            OcpfCandidateRow(
                cpf_id=int(cpf_id_value),
                first_name=_cell_str(field("Candidate First Name")),
                last_name=_cell_str(field("Candidate Last Name")),
                street_address=_cell_str(field("Candidate Street Address")),
                city=_cell_str(field("Candidate City")),
                state=_cell_str(field("Candidate State")),
                zip_code=_cell_str(field("Candidate Zip Code")),
                district_code_sought=district_code_sought,
                office_type_sought=_cell_str(field("Office Type Sought")),
                district_name_sought=_cell_str(field("District Name Sought")),
                closed_date=_cell_str(field("Closed Date")),
                party_affiliation=_cell_str(field("Party Affiliation")),
            )
        )
    return tuple(candidates)


class OcpfFilersSource(MaPublicBytesSource):
    url = OCPF_FILERS_URL

    def parse(self, content: bytes) -> tuple[OcpfCandidateRow, ...]:
        return parse_candidate_filers(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_filers.py -v --no-migrations`
Expected: PASS (4 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/source_records.py backend/cm2_ma/sources/ocpf_filers.py backend/cm2_ma/tests/test_ocpf_filers.py
git commit -m "feat(cm2_ma): parse OCPF candidate-filer bulk data"
```

---

### Task 3: OCPF candidate identity pool

**Files:**
- Create: `backend/cm2_ma/mapping/__init__.py`
- Create: `backend/cm2_ma/mapping/ocpf_pool.py`
- Test: `backend/cm2_ma/tests/test_ocpf_pool.py`

**Interfaces:**
- Consumes: `cm2_ma.source_records.{OcpfDistrict, OcpfCandidateRow}` (Tasks 1-2).
- Produces: `cm2_ma.mapping.ocpf_pool.OcpfCandidatePool` — `OcpfCandidatePool.build(*, districts: tuple[OcpfDistrict, ...], candidates: tuple[OcpfCandidateRow, ...]) -> OcpfCandidatePool` (classmethod), and instance method `find_by_name_and_district_code(self, *, full_name: str, district_code: int) -> OcpfCandidateRow | None`. Consumed by a later plan (Secretary candidate-page matching — not part of this plan).

**Design note carried from the spec**: `district_code` alone (not `district_code` + a separate office-type string) is sufficient to match any office, because OCPF's own scheme already folds office identity into the district slot for non-geographic offices — confirmed live: district code `1114` maps to `Office_Type_Description="Statewide"`, `District_Description="Auditor"` (the "district" IS the office name for statewide seats). So the matching interface takes only `district_code`, not a separate office parameter — this keeps Plan 2 self-contained without needing the Secretary-side office-name normalization a later plan will build.

**Matching is intentionally simple and conservative**: exact case-insensitive match on `"first last"` (normalized whitespace), scoped to the given `district_code`, among candidates with an empty `Closed Date`. Zero or multiple matches both return `None` — this defers to the fallback provisional-identity path a later plan builds, rather than guessing. This is a known, documented limitation (no fuzzy/partial name matching, no handling of "Steven J. Angelo" vs "Steven Angelo") to be revisited once a later plan can test it against real paired Secretary-vs-OCPF data — do not over-build it here.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_ocpf_pool.py`:
```python
from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict

_DISTRICTS = (
    OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
    OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
)


def _candidate(**overrides) -> OcpfCandidateRow:
    defaults = dict(
        cpf_id=10010,
        first_name="Steven",
        last_name="Angelo",
        street_address="39 Popmonet Rd",
        city="E. Falmouth",
        state="MA",
        zip_code="02536",
        district_code_sought=231,
        office_type_sought="House",
        district_name_sought="9th Essex",
        closed_date="",
        party_affiliation="Democratic",
    )
    defaults.update(overrides)
    return OcpfCandidateRow(**defaults)


def test_finds_exact_active_match_by_name_and_district_code():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is not None
    assert match.cpf_id == 10010


def test_match_is_case_and_whitespace_insensitive():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="  steven   ANGELO ", district_code=231)

    assert match is not None
    assert match.cpf_id == 10010


def test_closed_candidates_are_excluded_from_matching():
    closed = _candidate(cpf_id=10025, closed_date="7/12/2013")
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(closed,))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is None


def test_wrong_district_code_does_not_match():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=1114)

    assert match is None


def test_ambiguous_same_name_same_district_returns_none():
    same_name_twice = (
        _candidate(cpf_id=10010),
        _candidate(cpf_id=99999),
    )
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=same_name_twice)

    match = pool.find_by_name_and_district_code(full_name="Steven Angelo", district_code=231)

    assert match is None


def test_no_match_returns_none_not_an_error():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_candidate(),))

    match = pool.find_by_name_and_district_code(full_name="Nobody Here", district_code=231)

    assert match is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_pool.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.mapping'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/mapping/__init__.py`:
```python
```
(empty, matching `cm2_nc/mapping/__init__.py`)

`backend/cm2_ma/mapping/ocpf_pool.py`:
```python
from dataclasses import dataclass

from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict


def _normalize_name(first_name: str, last_name: str) -> str:
    return " ".join(f"{first_name} {last_name}".casefold().split())


@dataclass(frozen=True, slots=True)
class OcpfCandidatePool:
    """
    In-memory matching aid combining OCPF's district-code reference table
    and its "plausibly active" (Closed Date empty) candidate-filer pool.

    Never persists anything -- a later plan queries this to pre-resolve
    candidate identity while building Secretary-page CandidateFilingRecords.
    See docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md, "Candidate
    identity: OCPF as source, Secretary as confirmation".
    """

    districts: dict[int, OcpfDistrict]
    active_candidates: tuple[OcpfCandidateRow, ...]

    @classmethod
    def build(
        cls,
        *,
        districts: tuple[OcpfDistrict, ...],
        candidates: tuple[OcpfCandidateRow, ...],
    ) -> "OcpfCandidatePool":
        district_by_code = {district.district_code: district for district in districts}
        active = tuple(candidate for candidate in candidates if not candidate.closed_date)
        return cls(districts=district_by_code, active_candidates=active)

    def find_by_name_and_district_code(
        self, *, full_name: str, district_code: int
    ) -> OcpfCandidateRow | None:
        target_name = " ".join(full_name.casefold().split())
        matches = [
            candidate
            for candidate in self.active_candidates
            if candidate.district_code_sought == district_code
            and _normalize_name(candidate.first_name, candidate.last_name) == target_name
        ]
        if len(matches) != 1:
            return None
        return matches[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_ocpf_pool.py -v --no-migrations`
Expected: PASS (6 tests)

Then run the full plan's test suite together:
Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/ -v --no-migrations`
Expected: PASS (all tests from Plan 1 + Plan 2 — 18 + 15 = 33 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/mapping/__init__.py backend/cm2_ma/mapping/ocpf_pool.py backend/cm2_ma/tests/test_ocpf_pool.py
git commit -m "feat(cm2_ma): build OCPF candidate identity matching pool"
```

---

## Definition of done

- `docker compose -f docker-compose.v2.yaml run --rm test python manage.py check --settings=config.settings.v2` passes.
- `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/ -v --no-migrations` passes (33 tests: 18 from Plan 1 + 15 from this plan).
- `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma` passes.
- `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_core/tests/test_foundation.py -v --no-migrations` still passes (confirms this plan didn't regress Plan 1's final-review fix).
- No changes outside `backend/cm2_ma/`.
- `core/cf_solver.py` and `cloudflare/cf-solver/` are untouched.

## Next

A later plan (Secretary candidate-page parsing → `PreElectionBatch`) consumes `OcpfCandidatePool.find_by_name_and_district_code()` to pre-resolve `CandidateFilingRecord.person_public_id` for confident matches, per the spec's "OCPF as source, Secretary as confirmation" design. That plan also owns: normalizing the Secretary's office-name text (`<h2>`) and district text (`<h3>`) into an OCPF `district_code` to call this pool with, the suffix-aware name/address split for Secretary candidate rows, and the `no_nominations` notice handling. None of that is part of this plan.
