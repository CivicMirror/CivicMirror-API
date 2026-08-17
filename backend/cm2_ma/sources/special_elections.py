import hashlib
import re
from datetime import date

from bs4 import BeautifulSoup

from cm2_ingestion.contracts import ElectionRecord
from cm2_ma.constants import SEC_BASE_URL, SPECIAL_ELECTIONS_INDEX_URL

from .solver import MaSolverBytesSource
from .upcoming_elections import _parse_date

# Matches the Secretary's "current" special-election calendar pages, e.g.
# "/divisions/elections/recent-updates/current-special-election7.htm". These
# page numbers are not stable identifiers -- they shift as specials open and
# close (confirmed live: the same URL served a different special's calendar
# than the index page currently links to it under) -- so the index must
# always be crawled fresh rather than any specific URL being hardcoded.
_CURRENT_SPECIAL_HREF_RE = re.compile(
    r"^/divisions/elections/recent-updates/current-special-election\d+\.htm$"
)


def parse_special_elections_index(content: bytes) -> tuple[str, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    seen: set[str] = set()
    hrefs: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if _CURRENT_SPECIAL_HREF_RE.match(href) and href not in seen:
            seen.add(href)
            hrefs.append(href)
    return tuple(f"{SEC_BASE_URL}{href}" for href in sorted(hrefs))


class MaSpecialElectionsIndexSource(MaSolverBytesSource):
    url = SPECIAL_ELECTIONS_INDEX_URL

    def parse(self, content: bytes) -> tuple[str, ...]:
        return parse_special_elections_index(content)


_VACANCY_STRIP_RE = re.compile(r"^[()]+|[()]+$")


def _district_label(heading_text: str) -> str:
    stripped = re.sub(r"^Special State Election\s*", "", heading_text).strip()
    return stripped or heading_text


def _special_election_public_id(
    *, election_date: date, election_type: str, district_label: str
) -> str:
    normalized_label = " ".join(district_label.casefold().split())
    digest = hashlib.sha256(f"{election_type}|{normalized_label}".encode()).hexdigest()[:12]
    return f"ma/election/{election_date.isoformat()}/{election_type}/{digest}"


def parse_special_election_calendar(
    content: bytes,
    *,
    source_artifact_public_id: str | None = None,
) -> tuple[ElectionRecord, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    heading = soup.find("h1")
    if heading is None:
        return ()

    heading_text = " ".join(heading.get_text(" ", strip=True).split())
    district_label = _district_label(heading_text)

    vacancy_paragraph = heading.find_next("p")
    vacancy_reason = ""
    if vacancy_paragraph is not None:
        vacancy_reason = _VACANCY_STRIP_RE.sub(
            "", vacancy_paragraph.get_text(" ", strip=True)
        ).strip()

    records = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        label_text = cells[1].get_text(" ", strip=True)
        election_date = _parse_date(date_text)
        if election_date is None:
            continue
        if label_text == "State Primary":
            election_type = "special_primary"
            type_label = "Special Primary"
        elif label_text == "State Election":
            election_type = "special_general"
            type_label = "Special Election"
        else:
            continue

        name = f"Massachusetts {type_label} — {district_label}"
        if vacancy_reason:
            name = f"{name} ({vacancy_reason})"

        public_id = _special_election_public_id(
            election_date=election_date,
            election_type=election_type,
            district_label=district_label,
        )
        records.append(
            ElectionRecord(
                public_id=public_id,
                name=name,
                election_date=election_date,
                election_type=election_type,
                lifecycle_status="upcoming",
                source_key=f"special:{election_date.isoformat()}:{public_id.rsplit('/', 1)[-1]}",
                source_artifact_public_id=source_artifact_public_id,
            )
        )
    return tuple(sorted(records, key=lambda record: (record.election_date, record.name)))


class MaSpecialElectionCalendarSource(MaSolverBytesSource):
    def __init__(self, *, url: str, client=None):
        super().__init__(client=client)
        self.url = url

    def parse(self, content: bytes) -> tuple[ElectionRecord, ...]:
        return parse_special_election_calendar(content)
