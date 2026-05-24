"""
PDF parsers for Iowa SOS documents.

Uses pdfplumber for table extraction. Both parsers are tolerant of minor
format variations and log debug information to help diagnose layout changes.
"""
import logging
import re
from io import BytesIO

logger = logging.getLogger(__name__)

# Regex patterns for recognising election date lines in the calendar PDF
_DATE_RE = re.compile(
    r"""
    (?P<month>January|February|March|April|May|June|
              July|August|September|October|November|December)
    \s+
    (?P<day>\d{1,2}),?\s+
    (?P<year>20\d{2})
    """,
    re.VERBOSE | re.IGNORECASE,
)

_ELECTION_KEYWORDS = re.compile(
    r"\b(primary|general|special|municipal|school|city|runoff|election)\b",
    re.IGNORECASE,
)

# Header cells that identify the candidate list table
_CANDIDATE_HEADERS = {"office", "candidate", "name", "party"}


def parse_calendar_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Parse the Iowa 3-year election calendar PDF.

    Returns a list of dicts:
        {
            "name": str,              # e.g. "2026 Primary Election"
            "election_date": str,     # ISO date "YYYY-MM-DD"
            "election_year": int,
            "election_type": str,     # "primary" | "general" | "special" | "municipal" | "other"
            "filing_open": str | None,   # ISO date or None
            "filing_close": str | None,  # ISO date or None
        }
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("ia_sos.parsers: pdfplumber not installed")
        return []

    results = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                results.extend(_parse_calendar_text(text))
    except Exception as exc:
        logger.error("ia_sos.parsers.calendar_parse_error: %s", exc)
        return []

    # Deduplicate by name + date
    seen = set()
    deduped = []
    for row in results:
        key = (row["name"], row["election_date"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    logger.info("ia_sos.parsers.calendar_elections_found count=%d", len(deduped))
    return deduped


def _parse_calendar_text(text: str) -> list[dict]:
    """Extract election entries from a single page of calendar text."""
    results = []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        date_match = _DATE_RE.search(line)
        if not date_match:
            continue

        # Look for an election keyword on this line or adjacent lines
        context = " ".join(lines[max(0, i - 1): i + 3])
        if not _ELECTION_KEYWORDS.search(context):
            continue

        try:
            from datetime import datetime
            election_date = datetime.strptime(
                f"{date_match.group('month')} {date_match.group('day')} {date_match.group('year')}",
                "%B %d %Y",
            ).date()
        except ValueError:
            continue

        year = int(date_match.group("year"))

        # Infer election type from surrounding text
        election_type = _infer_election_type(context)

        # Build a human-readable name
        name = _build_election_name(context, year, election_type)

        results.append({
            "name": name,
            "election_date": election_date.isoformat(),
            "election_year": year,
            "election_type": election_type,
            "filing_open": None,
            "filing_close": None,
        })

    return results


def _infer_election_type(text: str) -> str:
    lower = text.lower()
    if "primary" in lower:
        return "primary"
    if "general" in lower:
        return "general"
    if "special" in lower:
        return "special"
    if "municipal" in lower or "city" in lower:
        return "municipal"
    if "school" in lower:
        return "school"
    if "runoff" in lower:
        return "runoff"
    return "other"


def _build_election_name(context: str, year: int, election_type: str) -> str:
    # Use the first line of context that contains an election keyword
    for line in context.splitlines():
        if _ELECTION_KEYWORDS.search(line):
            name = line.strip()
            if str(year) not in name:
                name = f"{year} {name}"
            return name
    return f"{year} Iowa {election_type.title()} Election"


# ---------------------------------------------------------------------------
# Candidate list PDF parser
# ---------------------------------------------------------------------------

def parse_candidate_list_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Parse an Iowa SOS candidate list PDF.

    Returns a list of candidate dicts:
        {
            "office": str,
            "candidate_name": str,
            "party": str,
            "district": str,    # county, district number, or empty
        }

    The Iowa SOS candidate list PDF is a tabular document. Each row is one
    candidate. Header rows identifying the table are skipped automatically.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("ia_sos.parsers: pdfplumber not installed")
        return []

    rows = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_rows = _extract_candidate_rows(page, page_num)
                rows.extend(page_rows)
    except Exception as exc:
        logger.error("ia_sos.parsers.candidate_parse_error: %s", exc)
        return []

    logger.info("ia_sos.parsers.candidate_rows_found count=%d", len(rows))
    return rows


def _extract_candidate_rows(page, page_num: int) -> list[dict]:
    """Extract candidate rows from one PDF page using table extraction."""
    tables = page.extract_tables()
    if not tables:
        # Fall back to text extraction if no table structure found
        return _extract_candidate_rows_from_text(page.extract_text() or "", page_num)

    rows = []
    for table in tables:
        if not table:
            continue

        # Find the header row index and column mapping
        header_idx, col_map = _find_header(table)
        if col_map is None:
            logger.debug("ia_sos.parsers.no_header page=%d", page_num)
            continue

        for row in table[header_idx + 1:]:
            if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            candidate = _map_row(row, col_map)
            if candidate:
                rows.append(candidate)

    return rows


def _find_header(table: list[list]) -> tuple[int, dict | None]:
    """
    Find the header row in a table and return its index and column mapping.
    Returns (index, {col_name: col_index}) or (-1, None).
    """
    for idx, row in enumerate(table):
        if row is None:
            continue
        normalized = {
            str(cell).strip().lower()
            for cell in row
            if cell is not None and str(cell).strip()
        }
        # Require at least 2 of the expected header words
        if len(normalized & _CANDIDATE_HEADERS) >= 2:
            col_map = {}
            for col_idx, cell in enumerate(row):
                if cell is None:
                    continue
                key = str(cell).strip().lower()
                if "office" in key:
                    col_map["office"] = col_idx
                elif "candidate" in key or "name" in key:
                    col_map["candidate_name"] = col_idx
                elif "party" in key:
                    col_map["party"] = col_idx
                elif "district" in key or "county" in key:
                    col_map["district"] = col_idx
            return idx, col_map if col_map else None
    return -1, None


def _map_row(row: list, col_map: dict) -> dict | None:
    """Map a table row to a candidate dict using the column mapping."""
    def cell(key: str) -> str:
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

    office = cell("office")
    candidate_name = cell("candidate_name")

    if not office and not candidate_name:
        return None

    return {
        "office": office,
        "candidate_name": candidate_name,
        "party": cell("party"),
        "district": cell("district"),
    }


def _extract_candidate_rows_from_text(text: str, page_num: int) -> list[dict]:
    """
    Fallback: attempt to extract candidate rows from raw page text when
    pdfplumber finds no table structure.
    """
    logger.debug("ia_sos.parsers.text_fallback page=%d", page_num)
    rows = []
    current_office = ""

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Lines that look like office headings (all caps or title-case, no party keyword)
        if line.isupper() and len(line) > 3:
            current_office = line.title()
            continue
        # Lines with a party abbreviation: REP, DEM, NP, LIB, etc.
        parts = line.rsplit(None, 1)
        if len(parts) == 2 and parts[1].upper() in {"REP", "DEM", "NP", "IND", "LIB", "GRN"}:
            rows.append({
                "office": current_office,
                "candidate_name": parts[0].strip(),
                "party": parts[1].upper(),
                "district": "",
            })

    return rows
