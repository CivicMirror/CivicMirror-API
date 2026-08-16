import hashlib
import re
from datetime import date

from bs4 import BeautifulSoup

from cm2_ingestion.contracts import ElectionRecord
from cm2_nc.constants import UPCOMING_ELECTIONS_URL

from .http import NcPublicBytesSource

_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _election_type(label: str) -> str:
    normalized = " ".join(label.casefold().split())
    if "second primary" in normalized or "primary runoff" in normalized:
        return "primary_runoff"
    if "general runoff" in normalized:
        return "general_runoff"
    if "primary" in normalized:
        return "primary"
    if "general" in normalized:
        return "general"
    if "municipal" in normalized:
        return "municipal"
    if "special" in normalized:
        return "special"
    return "other"


def _section_text(heading) -> str:
    parts = []
    for sibling in heading.next_siblings:
        name = getattr(sibling, "name", None)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            break
        get_text = getattr(sibling, "get_text", None)
        if get_text:
            parts.append(get_text(" ", strip=True))
    return " ".join(parts)


def _parse_date(text: str) -> date | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    month_label, day, year = match.groups()
    month = _MONTHS[month_label.casefold().rstrip(".")]
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _election_public_id(*, election_date: date, election_type: str, label: str) -> str:
    normalized_label = " ".join(label.casefold().split())
    digest = hashlib.sha256(normalized_label.encode()).hexdigest()[:12]
    return f"nc/election/{election_date.isoformat()}/{election_type}/{digest}"


def parse_upcoming_elections(
    content: bytes,
    *,
    source_artifact_public_id: str | None = None,
) -> tuple[ElectionRecord, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    records = []
    seen: set[tuple[date, str, str]] = set()
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        label = " ".join(heading.get_text(" ", strip=True).split())
        if not re.search(r"\belection\b", label, re.IGNORECASE):
            continue
        election_date = _parse_date(_section_text(heading))
        if election_date is None:
            continue
        election_type = _election_type(label)
        identity = (election_date, election_type, label.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        public_id = _election_public_id(
            election_date=election_date,
            election_type=election_type,
            label=label,
        )
        records.append(
            ElectionRecord(
                public_id=public_id,
                name=label,
                election_date=election_date,
                election_type=election_type,
                lifecycle_status="upcoming",
                source_key=f"upcoming:{election_date.isoformat()}:{public_id.rsplit('/', 1)[-1]}",
                source_artifact_public_id=source_artifact_public_id,
            )
        )
    return tuple(sorted(records, key=lambda record: (record.election_date, record.name)))


class NcUpcomingElectionsSource(NcPublicBytesSource):
    url = UPCOMING_ELECTIONS_URL

    def parse(self, content: bytes) -> tuple[ElectionRecord, ...]:
        return parse_upcoming_elections(content)
