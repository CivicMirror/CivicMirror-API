"""
HTML parsers for Colorado SOS candidate list pages.

Parses the structured HTML table at:
  https://www.coloradosos.gov/pubs/elections/vote/primaryCandidates.html

Table columns: Candidate name | Office | District | Party | Write in?

Withdrawn candidates are denoted by inline CSS:
  <span style="text-decoration: line-through;">...</span>
If any cell in a row carries that style, the entire row is treated as withdrawn.
"""
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_STRIKE_STYLE = "text-decoration: line-through"


def _is_struck(cell) -> bool:
    """Return True if a BeautifulSoup <td> cell carries the strikethrough style."""
    span = cell.find("span", style=lambda s: s and _STRIKE_STYLE in s)
    return span is not None


def parse_candidate_table(html: str) -> list[dict]:
    """
    Parse the CO SOS candidate list HTML page.

    Returns a list of dicts:
        {
            "candidate_name": str,
            "office": str,
            "district": str,       # "Statewide" or a numeric district string
            "party": str,          # e.g. "Democratic Party"
            "is_write_in": bool,
            "is_withdrawn": bool,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        logger.warning("co_sos.parsers: no table found in candidate HTML")
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    # Identify header row to find column positions
    header_row = rows[0]
    headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]

    try:
        idx_name = headers.index("candidate name")
        idx_office = headers.index("office")
        idx_district = headers.index("district")
        idx_party = headers.index("party")
        idx_write_in = headers.index("write in?")
    except ValueError as exc:
        logger.warning("co_sos.parsers: unexpected header layout: %s — %s", headers, exc)
        return []

    results = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # A row is withdrawn if any cell carries the strikethrough style
        is_withdrawn = any(_is_struck(cells[i]) for i in range(len(cells)))

        # Extract text from each cell (strips the <span> wrapper too)
        candidate_name = cells[idx_name].get_text(strip=True)
        office = cells[idx_office].get_text(strip=True)
        district = cells[idx_district].get_text(strip=True)
        party = cells[idx_party].get_text(strip=True)
        is_write_in = cells[idx_write_in].get_text(strip=True).upper() == "Y"

        if not candidate_name:
            continue

        results.append({
            "candidate_name": candidate_name,
            "office": office,
            "district": district,
            "party": party,
            "is_write_in": is_write_in,
            "is_withdrawn": is_withdrawn,
        })

    logger.info("co_sos.parsers: parsed %d candidates", len(results))
    return results
