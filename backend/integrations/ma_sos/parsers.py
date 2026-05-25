"""
HTML and CSV parsers for Massachusetts SOS (electionstats.state.ma.us).

HTML parsing uses BeautifulSoup; CSV parsing uses the standard csv module
(required because numeric values ≥1000 are comma-formatted and quoted:
"2,041,668" — naive str.split() would corrupt those values).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Synthetic tally rows in election CSVs — not real candidates
TALLY_LABELS = frozenset({"All Others", "Blanks", "Total Votes Cast", "Write-In"})

# Regex for inline JS election_data object on BQ view pages.
# Matches: election_data[11620] = {Election: {"id": "11620", ...}}
_BQ_DATA_RE = re.compile(
    r'election_data\[(\d+)\]\s*=\s*\{Election:\s*(\{.*?\})\s*\}',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Election search page
# ---------------------------------------------------------------------------

def parse_election_search_html(html: str) -> list[dict]:
    """
    Parse the electionstats election search results page.

    Returns a list of dicts:
        {"election_id": int, "office": str, "district": str}

    The stage and year fields are added by the client after the fact.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = []

    for tr in soup.find_all("tr", id=re.compile(r"^election-id-\d+$")):
        row_id = tr.get("id", "")
        m = re.search(r"election-id-(\d+)", row_id)
        if not m:
            continue
        election_id = int(m.group(1))

        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # Columns: td[0]=year, td[1]=office, td[2]=district, td[3]=stage (optional)
        office = tds[1].get_text(strip=True)
        district = tds[2].get_text(strip=True) if len(tds) > 2 else ""

        rows.append({
            "election_id": election_id,
            "office": office,
            "district": district,
        })

    logger.debug("ma_sos.parsers.parse_election_search count=%d", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Ballot question search page
# ---------------------------------------------------------------------------

def parse_bq_search_html(html: str) -> list[int]:
    """
    Parse the electionstats BQ search results page.

    Returns a list of ballot question ID ints (from tr[id^="bq-id-"] rows).
    """
    soup = BeautifulSoup(html, "lxml")
    bq_ids: list[int] = []

    for tr in soup.find_all("tr", id=re.compile(r"^bq-id-\d+$")):
        row_id = tr.get("id", "")
        m = re.search(r"bq-id-(\d+)", row_id)
        if m:
            bq_ids.append(int(m.group(1)))

    logger.debug("ma_sos.parsers.parse_bq_search count=%d", len(bq_ids))
    return bq_ids


# ---------------------------------------------------------------------------
# Ballot question metadata from JS
# ---------------------------------------------------------------------------

def parse_bq_metadata_js(html: str) -> dict:
    """
    Extract the inline election_data JS object from a BQ view page.

    The page contains JS like:
        election_data[11620] = {Election: {"id": "11620", "question_number": "1", ...}};

    Returns a dict with the parsed fields, or {} if not found.

    NOTE: The JSON inside uses standard double-quoted keys/values, so standard
    json.loads() works after extracting the inner {...} object.
    """
    m = _BQ_DATA_RE.search(html)
    if not m:
        logger.warning("ma_sos.parsers.parse_bq_metadata_js: no election_data found")
        return {}

    bq_id = int(m.group(1))
    raw_json = m.group(2).strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("ma_sos.parsers.parse_bq_metadata_js: JSON parse error bq_id=%d: %s", bq_id, exc)
        return {}

    # Normalize to known field names
    return {
        "bq_id": bq_id,
        "question_number": data.get("question_number", ""),
        "question": data.get("question", ""),
        "question_alias": data.get("question_alias", ""),
        "summary": data.get("summary", ""),
        "date": data.get("date", ""),
        "year": int(data.get("year", 0) or 0),
        "is_initiative_petition": bool(data.get("is_initiative_petition", "")),
        "is_referendum": bool(data.get("is_referendum", "")),
        "is_local": bool(data.get("is_local", "")),
        "is_county": bool(data.get("is_county", "")),
        "n_yes_votes": _safe_int(data.get("n_yes_votes")),
        "n_no_votes": _safe_int(data.get("n_no_votes")),
        "n_blank_votes": _safe_int(data.get("n_blank_votes")),
    }


# ---------------------------------------------------------------------------
# Election results CSV
# ---------------------------------------------------------------------------

def parse_election_csv(csv_bytes: bytes) -> list[dict]:
    """
    Parse an electionstats election results CSV.

    CSV structure:
      Row 0: "City/Town",,"","Candidate A","Candidate B",...,"All Others","Blanks","Total Votes Cast"
      Row 1: "",,"","Democratic","Republican",...
      Data rows: "Abington",,"","4,714","4,639",...
      Final row: "TOTALS",,"","2,126,518",...

    Returns a list of candidate dicts (TOTALS row and tally labels are included
    for aggregates; callers filter out TALLY_LABELS as needed):
        {
            "name": str,        # candidate name from row 0
            "party": str,       # party from row 1
            "col_index": int,   # 0-based column index in the data columns
        }

    Also returns per-town vote data in the "towns" list attached to each dict.
    For our purposes (upsert candidate records), only name/party/col_index are needed.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)

    if len(all_rows) < 2:
        logger.warning("ma_sos.parsers.parse_election_csv: insufficient rows (%d)", len(all_rows))
        return []

    header_row = all_rows[0]
    party_row = all_rows[1]

    # Columns 0-2 are: City/Town, ward placeholder, precinct placeholder
    DATA_COL_OFFSET = 3

    candidates = []
    for col_idx in range(DATA_COL_OFFSET, len(header_row)):
        name = header_row[col_idx].strip().replace("\n", " ").replace("\r", "")
        if not name:
            continue
        party = ""
        if col_idx < len(party_row):
            party = party_row[col_idx].strip()

        candidates.append({
            "name": name,
            "party": party,
            "col_index": col_idx,
        })

    logger.debug("ma_sos.parsers.parse_election_csv: parsed %d candidate columns", len(candidates))
    return candidates


def parse_election_csv_totals(csv_bytes: bytes) -> dict[str, int]:
    """
    Extract the TOTALS row vote counts from an election CSV.

    Returns: {"Candidate Name": vote_count, ...}
    Tally labels (All Others, Blanks, Total Votes Cast) are included.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)

    if len(all_rows) < 2:
        return {}

    header_row = all_rows[0]
    DATA_COL_OFFSET = 3

    # Find TOTALS row (last data row)
    totals_row = None
    for row in reversed(all_rows):
        if row and row[0].strip().upper() == "TOTALS":
            totals_row = row
            break

    if not totals_row:
        return {}

    result = {}
    for col_idx in range(DATA_COL_OFFSET, len(header_row)):
        name = header_row[col_idx].strip()
        if not name:
            continue
        if col_idx < len(totals_row):
            result[name] = _parse_vote_count(totals_row[col_idx])

    return result


# ---------------------------------------------------------------------------
# Ballot question CSV
# ---------------------------------------------------------------------------

def parse_bq_csv(csv_bytes: bytes) -> dict[str, int]:
    """
    Parse a ballot question results CSV.

    CSV structure:
      Row 0: "Locality",,"","Yes","No","Blanks","Total Votes Cast"
      Data rows: "Barnstable",,"","18,328","8,097","1,572","27,997"
      Final row: "TOTALS",,"","2,326,911","924,289","261,730","3,512,930"

    Returns the TOTALS row as: {"Yes": int, "No": int, "Blanks": int, "Total Votes Cast": int}
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)

    if len(all_rows) < 2:
        return {}

    header_row = all_rows[0]
    DATA_COL_OFFSET = 3

    # Find TOTALS row
    totals_row = None
    for row in reversed(all_rows):
        if row and row[0].strip().upper() == "TOTALS":
            totals_row = row
            break

    if not totals_row:
        return {}

    result = {}
    for col_idx in range(DATA_COL_OFFSET, len(header_row)):
        label = header_row[col_idx].strip()
        if label and col_idx < len(totals_row):
            result[label] = _parse_vote_count(totals_row[col_idx])

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_vote_count(raw: str) -> int:
    """Parse a potentially comma-formatted vote count string to int."""
    cleaned = raw.strip().replace(",", "").replace('"', "")
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def _safe_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return 0
