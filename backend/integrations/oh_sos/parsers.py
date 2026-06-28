"""
Parser for Ohio SOS CFDISCLOSURE ACT_CAN_LIST.CSV.

Column layout (0-indexed):
  [0]  COM_NAME             — committee name (e.g. "CITIZENS FOR KALMBACH")
  [1]  MASTER_KEY           — CFDISCLOSURE committee ID
  [2]  COM_ADDRESS
  [3]  COM_CITY
  [4]  COM_STATE
  [5]  COM_ZIP
  [6]  TREA_FIRST_NAME      — treasurer first name
  [7]  TREA_LAST_NAME
  [8]  TREA_MIDDLE_NAME
  [9]  TREA_SUFFIX
  [10] TREA_ADDRESS
  [11] TREA_CITY
  [12] TREA_STATE
  [13] TREA_ZIP
  [14] DEP_FIRST_NAME       — deputy treasurer
  [15] DEP_LAST_NAME
  [16] CANDIDATE_FIRST_NAME
  [17] CANDIDATE_LAST_NAME
  [18] OFFICE               — office type (HOUSE, SENATE, GOVERNOR, ...)
  [19] DISTRICT             — district number for legislative/judicial races
  [20] OFFICE (dup header)  — actually PARTY (REPUBLICAN, DEMOCRAT, ...)
  [21] SPONSOR

Note: col[20] is named "OFFICE" in the CSV header (duplicate) but contains
party affiliation. We access all columns by index to avoid DictReader collision.
"""
import csv
import io
import logging

logger = logging.getLogger(__name__)

# Offices we skip entirely (retirement boards, pension funds, undeclared)
_SKIP_OFFICES = frozenset({
    "UNDECLARED",
    "STATE TEACHERS RETIREMENT",
    "SCHOOL EMPLOYEES RETIREMENT",
    "POLICE AND FIRE PENSION FUND",
    "PUBLIC EMPLOYEES RETIREMENT",
})


def parse_active_candidates(csv_text: str) -> list[dict]:
    """
    Parse the ACT_CAN_LIST.CSV text and return a list of candidate dicts.

    Each dict has:
        candidate_first_name, candidate_last_name, office, district, party,
        master_key, committee_name
    """
    reader = csv.reader(io.StringIO(csv_text, newline=""))
    try:
        next(reader)  # skip header row
    except StopIteration:
        logger.warning("oh_sos.parser: empty CSV")
        return []

    candidates = []
    skipped = 0

    for i, row in enumerate(reader, start=2):
        if len(row) < 21:
            logger.debug("oh_sos.parser: short row %d (len=%d) — skipped", i, len(row))
            skipped += 1
            continue

        office = row[18].strip()
        if not office or office in _SKIP_OFFICES:
            skipped += 1
            continue

        first = row[16].strip()
        last = row[17].strip()
        if not last:
            skipped += 1
            continue

        candidates.append({
            "candidate_first_name": first,
            "candidate_last_name": last,
            "office": office,
            "district": row[19].strip(),
            "party": row[20].strip(),
            "master_key": row[1].strip(),
            "committee_name": row[0].strip(),
        })

    logger.info(
        "oh_sos.parser: parsed=%d skipped=%d", len(candidates), skipped
    )
    return candidates
