import re

from bs4 import BeautifulSoup

from cm2_ma.constants import SEC_BASE_URL, SPECIAL_ELECTIONS_INDEX_URL

from .solver import MaSolverBytesSource

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
