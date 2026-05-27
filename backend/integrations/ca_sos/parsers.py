"""
Parsers for California SOS endpoint catalog CSV files.

The CA SOS media portal publishes a CSV file (json-endpoints.csv) listing all
available JSON API endpoints for the current election. This file changes each
election cycle as contest IDs and contest names are updated.

Example csv format (tab or comma separated, may vary per election):
  RaceID,ContestName,EndpointURL,ContestType
  02000000000059,Governor - Statewide Results,/returns/governor,Candidate
  ...

The parser is deliberately lenient: it tries multiple column header spellings
and skips rows it cannot interpret rather than raising.
"""
import csv
import io
import logging
import re

logger = logging.getLogger(__name__)

# Known column header aliases (lowercase)
_URL_HEADERS = {"endpointurl", "url", "jsonurl", "endpoint", "endpoint_url"}
_NAME_HEADERS = {"contestname", "racetitle", "name", "contest", "race"}
_TYPE_HEADERS = {"contesttype", "type", "racetype", "contest_type"}
_ID_HEADERS = {"raceid", "contestid", "id", "race_id"}

# Paths that are clearly not results endpoints
_SKIP_PATH_PATTERNS = [
    re.compile(r"\.csv$", re.I),
    re.compile(r"\.pdf$", re.I),
    re.compile(r"\.xlsx$", re.I),
    re.compile(r"/query", re.I),
    re.compile(r"/status", re.I),
]


def _find_col(headers: list[str], aliases: set[str]) -> int | None:
    for i, h in enumerate(headers):
        if h.strip().lower().replace(" ", "") in aliases:
            return i
    return None


def _is_measure(contest_type: str) -> bool:
    return "measure" in contest_type.lower() or "referendum" in contest_type.lower()


def _should_skip(path: str) -> bool:
    return any(pat.search(path) for pat in _SKIP_PATH_PATTERNS)


def parse_endpoint_catalog(csv_bytes: bytes) -> list[dict]:
    """
    Parse the CA SOS endpoint catalog CSV into a list of contest dicts.

    Each dict has:
      - "name"    : str  — human-readable contest name
      - "path"    : str  — API path, e.g. "/returns/governor"
      - "type"    : str  — "candidate" or "measure"
      - "race_id" : str  — source RaceID (may be empty string)
    """
    try:
        text = csv_bytes.decode("utf-8-sig", errors="replace")
    except Exception:
        text = csv_bytes.decode("latin-1", errors="replace")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        logger.warning("ca_sos.parser.empty_catalog")
        return []

    headers = rows[0]
    url_col = _find_col(headers, _URL_HEADERS)
    name_col = _find_col(headers, _NAME_HEADERS)
    type_col = _find_col(headers, _TYPE_HEADERS)
    id_col = _find_col(headers, _ID_HEADERS)

    if url_col is None:
        logger.warning(
            "ca_sos.parser.no_url_column headers=%s", headers
        )
        return []

    results = []
    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(cell.strip() == "" for cell in row):
            continue

        try:
            path = row[url_col].strip()
        except IndexError:
            continue

        if not path or _should_skip(path):
            continue

        # Ensure path starts with /
        if not path.startswith("/"):
            path = f"/{path}"

        name = row[name_col].strip() if name_col is not None and name_col < len(row) else path
        raw_type = row[type_col].strip() if type_col is not None and type_col < len(row) else ""
        race_id = row[id_col].strip() if id_col is not None and id_col < len(row) else ""

        results.append({
            "name": name,
            "path": path,
            "type": "measure" if _is_measure(raw_type) else "candidate",
            "race_id": race_id,
        })

    logger.info("ca_sos.parser.catalog_parsed contests=%d", len(results))
    return results


def deduplicate_catalog(entries: list[dict]) -> list[dict]:
    """Remove duplicate paths, keeping first occurrence."""
    seen: set[str] = set()
    out = []
    for entry in entries:
        if entry["path"] not in seen:
            seen.add(entry["path"])
            out.append(entry)
    return out
