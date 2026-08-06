from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urljoin

_REPORT_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]*CandidateFiling\.aspx\?elid=(?P<elid>\d+))"[^>]*>\s*Candidate Report\s*</a>',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HawaiiCandidateRow:
    contest: str
    party: str
    ballot_name: str
    legal_name: str
    mailing_address: str
    city_state_zip: str
    phone: str
    email: str
    website: str
    issue_date: date | None
    filing_date: date | None
    status: str
    raw: dict[str, str] = field(default_factory=dict)


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_candidate_report_link(html: str, *, base_url: str = "https://elections.hawaii.gov") -> tuple[str, str]:
    match = _REPORT_LINK_RE.search(html or "")
    if not match:
        raise ValueError("candidate report link not found")
    href = match.group("href")
    elid = match.group("elid")
    return urljoin(base_url, href), elid


def parse_candidate_report_csv(csv_bytes: bytes | str) -> list[HawaiiCandidateRow]:
    text = csv_bytes.decode("utf-8-sig") if isinstance(csv_bytes, (bytes, bytearray)) else csv_bytes
    reader = csv.DictReader(io.StringIO(text))
    rows: list[HawaiiCandidateRow] = []

    for raw_row in reader:
        row = {key: (value or "").strip() for key, value in (raw_row or {}).items()}
        if not any(row.values()):
            continue
        rows.append(HawaiiCandidateRow(
            contest=row.get("Contests", ""),
            party=row.get("Party", ""),
            ballot_name=row.get("BallotName", ""),
            legal_name=row.get("LegalName", ""),
            mailing_address=row.get("MailingAddress", ""),
            city_state_zip=row.get("CityStateZip", ""),
            phone=row.get("Phone", ""),
            email=row.get("Email", ""),
            website=row.get("Website", ""),
            issue_date=_parse_date(row.get("IssueDate", "")),
            filing_date=_parse_date(row.get("FilingDate", "")),
            status=row.get("Status", ""),
            raw=row,
        ))

    return rows


def candidate_row_hash(row: HawaiiCandidateRow) -> str:
    payload = "|".join([
        row.contest,
        row.party,
        row.ballot_name,
        row.legal_name,
        row.mailing_address,
        row.city_state_zip,
        row.phone,
        row.email,
        row.website,
        row.issue_date.isoformat() if row.issue_date else "",
        row.filing_date.isoformat() if row.filing_date else "",
        row.status,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
