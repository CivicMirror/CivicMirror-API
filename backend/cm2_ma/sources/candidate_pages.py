import re

from bs4 import BeautifulSoup

from cm2_ma.source_records import SecretaryCandidateRow, SecretaryPageParseResult

from .solver import MaSolverBytesSource

_SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}
_NO_NOMINATIONS = "no nominations"


def _split_name_and_address(raw_line: str) -> tuple[str, str, str]:
    """
    Returns (reported_name, suffix, address). Handles the real edge case where
    a suffix creates an extra comma before the address starts, e.g.
    "Christopher A. Iannella, Jr., 263 Pond St., Boston" -- a naive split on
    the first comma would otherwise take the name as just "Christopher A.
    Iannella" and misplace "Jr." into the address.
    """
    parts = [part.strip() for part in raw_line.split(",")]
    if len(parts) >= 2 and parts[1].casefold().rstrip(".") in {s.rstrip(".") for s in _SUFFIXES}:
        suffix = parts[1]
        name = f"{parts[0]}, {suffix}"
        address = ", ".join(parts[2:])
        return name, suffix, address
    name = parts[0]
    address = ", ".join(parts[1:])
    return name, "", address


def _split_given_middle_family(name_without_suffix: str) -> tuple[str, str, str]:
    tokens = name_without_suffix.split()
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""
    given = tokens[0]
    family = tokens[-1]
    middle = " ".join(tokens[1:-1])
    return given, middle, family


def parse_candidate_page(content: bytes, *, party: str) -> SecretaryPageParseResult:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")

    candidates: list[SecretaryCandidateRow] = []
    no_nominations: list[tuple[str, str | None]] = []

    current_office: str | None = None
    current_district: str | None = None

    # Real Secretary candidate pages carry footer markup (address, phone,
    # "Connect with Us" heading, etc.) after the closing </article> tag that
    # wraps the actual office/candidate content. Scope the scan to that
    # <article> so footer h2/h3/p elements never get parsed as fake rows.
    # Fall back to the whole document when there's no <article> wrapper (as
    # in older fixtures / unexpected markup) so we still parse something.
    scope = soup.find("article") or soup

    for element in scope.find_all(re.compile(r"^(h2|h3|p)$")):
        if element.name == "h2":
            current_office = " ".join(element.get_text(" ", strip=True).split())
            current_district = None
            continue
        if element.name == "h3":
            current_district = " ".join(element.get_text(" ", strip=True).split())
            continue
        if current_office is None:
            continue

        raw_line = " ".join(element.get_text(" ", strip=True).split())
        if not raw_line:
            continue
        if raw_line.casefold() == _NO_NOMINATIONS:
            no_nominations.append((current_office, current_district))
            continue

        name_with_suffix, suffix, address = _split_name_and_address(raw_line)
        name_without_suffix = name_with_suffix[: -(len(suffix) + 2)] if suffix else name_with_suffix
        given, middle, family = _split_given_middle_family(name_without_suffix)

        candidates.append(
            SecretaryCandidateRow(
                office_label=current_office,
                district_label=current_district,
                party=party,
                raw_line=raw_line,
                reported_name=name_with_suffix,
                given_name=given,
                middle_name=middle,
                family_name=family,
                suffix=suffix,
                address=address,
            )
        )

    return SecretaryPageParseResult(
        candidates=tuple(candidates), no_nominations=tuple(no_nominations)
    )


class MaCandidatePageSource(MaSolverBytesSource):
    def __init__(self, *, url: str, party: str, client=None):
        super().__init__(client=client)
        self.url = url
        self.party = party

    def parse(self, content: bytes) -> SecretaryPageParseResult:
        return parse_candidate_page(content, party=self.party)
