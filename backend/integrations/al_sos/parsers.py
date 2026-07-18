from __future__ import annotations

import datetime as dt
import io
import re
from collections import defaultdict
from dataclasses import dataclass

from openpyxl import load_workbook
from results.adapters.base import ResultRow

from .exceptions import AlSosError

_PARTY_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{2,5})\)\s*$")


@dataclass(frozen=True)
class AlEnrParsedResult:
    rows: list[ResultRow]
    source_version: str
    is_complete: bool
    county_stats: dict[str, dict]


def normalize_contest_title(title: str) -> tuple[str, str]:
    normalized = " ".join(str(title or "").split())
    match = _PARTY_SUFFIX_RE.search(normalized)
    if not match:
        return normalized, ""
    return _PARTY_SUFFIX_RE.sub("", normalized).strip(), match.group(1)


def parse_enr_workbook(content: bytes) -> AlEnrParsedResult:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "AllResults" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing AllResults sheet")
    if "Statistics" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing Statistics sheet")

    county_stats = _parse_statistics(workbook["Statistics"])
    is_complete = all(
        stat["total_precincts"] == stat["precincts_reported"]
        for stat in county_stats.values()
        if stat["total_precincts"] is not None
    )
    result_type = "official" if is_complete else "unofficial"

    totals: dict[tuple[str, str, str, str], int] = defaultdict(int)
    metadata: dict[tuple[str, str, str, str], dict] = {}
    election_codes: set[str] = set()

    for raw in _iter_dict_rows(workbook["AllResults"]):
        contest_code = _clean(raw.get("Contest Code"))
        contest_title = _clean(raw.get("Contest Title"))
        candidate_name = _clean(raw.get("Candidate Name"))
        party_code = _clean(raw.get("Party Code"))
        votes = _safe_int(raw.get("Votes"))
        election_code = _clean(raw.get("Election Code"))
        county_code = _clean(raw.get("County Code"))
        if not contest_code or not contest_title or not candidate_name:
            continue

        office_title, party_from_title = normalize_contest_title(contest_title)
        party = party_code or party_from_title
        key = (contest_code, office_title, candidate_name, party)
        totals[key] += votes
        election_codes.add(election_code)
        metadata.setdefault(
            key,
            {
                "contest_code": contest_code,
                "contest_title": contest_title,
                "party_code": party,
                "source": "al_sos_enr",
                "county_codes": [],
            },
        )
        metadata[key]["county_codes"].append(county_code)

    rows = [
        ResultRow(
            office_title=office_title,
            candidate_name=None if _is_write_in(candidate_name) else candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type=result_type,
            is_write_in_aggregate=_is_write_in(candidate_name),
            raw=metadata[key],
        )
        for key, vote_count in sorted(totals.items(), key=lambda item: item[0])
        for _contest_code, office_title, candidate_name, _party in [key]
    ]

    return AlEnrParsedResult(
        rows=rows,
        source_version=_source_version(election_codes, county_stats, len(rows)),
        is_complete=is_complete,
        county_stats=county_stats,
    )


def _parse_statistics(sheet) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for raw in _iter_dict_rows(sheet):
        county_code = _clean(raw.get("County Code"))
        if not county_code:
            continue
        last_updated = raw.get("Last Updated")
        if isinstance(last_updated, dt.datetime):
            last_updated_value = last_updated.isoformat()
        else:
            last_updated_value = _clean(last_updated)
        stats[county_code] = {
            "ballots_cast": _safe_int(raw.get("Ballots Cast")),
            "total_precincts": _safe_int(raw.get("Total Precincts")),
            "precincts_reported": _safe_int(raw.get("Precincts Reported")),
            "last_updated": last_updated_value,
        }
    return stats


def _iter_dict_rows(sheet):
    rows = sheet.iter_rows(values_only=True)
    headers = [_clean(value) for value in next(rows, [])]
    for row in rows:
        yield dict(zip(headers, row))


def _source_version(election_codes: set[str], county_stats: dict[str, dict], row_count: int) -> str:
    code = ",".join(sorted(election_codes))
    latest = max((stat["last_updated"] for stat in county_stats.values()), default="")
    return f"{code}:{latest}:{row_count}"


def _safe_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(str(value).replace(",", "").strip())


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _is_write_in(value: str) -> bool:
    return "write-in" in value.lower() or "write in" in value.lower()
