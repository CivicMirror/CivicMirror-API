"""
Parser for the Florida Election Watch tab-delimited results file.

File format (header row always present, no brackets):
  ElectionDate  PartyCode  PartyName  RaceCode  RaceName  CountyCode  CountyName
  Juris1num  Juris2num  Precincts  PrecinctsReporting  CanNameLast  CanNameFirst
  CanNameMiddle  CanVotes

ElectionDate format: MM/DD/YYYY
Juris2num is frequently blank/whitespace.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class ElectionRow:
    election_date: date
    party_code: str
    party_name: str
    race_code: str
    race_name: str
    county_code: str
    county_name: str
    juris1_num: str
    juris2_num: str
    precincts: int
    precincts_reporting: int
    can_name_last: str
    can_name_first: str
    can_name_middle: str
    can_votes: int


def _parse_date(raw: str) -> date | None:
    """Parse MM/DD/YYYY into a date object."""
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def _safe_int(raw: str) -> int:
    try:
        return int(raw.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def parse_results_file(text: str) -> list[ElectionRow]:
    """
    Parse the full tab-delimited results file text into a list of ElectionRow.
    The first row is always the header and is skipped.
    """
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows: list[ElectionRow] = []

    for line_num, raw in enumerate(reader, start=2):
        election_date = _parse_date(raw.get("ElectionDate", ""))
        if election_date is None:
            logger.warning("fl_ew.parser.bad_date line=%d raw=%r", line_num, raw)
            continue

        try:
            rows.append(ElectionRow(
                election_date=election_date,
                party_code=(raw.get("PartyCode") or "").strip(),
                party_name=(raw.get("PartyName") or "").strip(),
                race_code=(raw.get("RaceCode") or "").strip(),
                race_name=(raw.get("RaceName") or "").strip(),
                county_code=(raw.get("CountyCode") or "").strip(),
                county_name=(raw.get("CountyName") or "").strip(),
                juris1_num=(raw.get("Juris1num") or "").strip(),
                juris2_num=(raw.get("Juris2num") or "").strip(),
                precincts=_safe_int(raw.get("Precincts", "0")),
                precincts_reporting=_safe_int(raw.get("PrecinctsReporting", "0")),
                can_name_last=(raw.get("CanNameLast") or "").strip(),
                can_name_first=(raw.get("CanNameFirst") or "").strip(),
                can_name_middle=(raw.get("CanNameMiddle") or "").strip(),
                can_votes=_safe_int(raw.get("CanVotes", "0")),
            ))
        except Exception as exc:
            logger.warning("fl_ew.parser.row_error line=%d err=%s", line_num, exc)
            continue

    logger.info("fl_ew.parser.parsed rows=%d", len(rows))
    return rows
