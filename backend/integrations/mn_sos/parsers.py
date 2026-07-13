"""
Parsers for Minnesota Secretary of State election-results file formats.

Confirmed live 2026-07-13 against the Nov 5, 2024 general election
(ersElectionId=170) — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md.
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def parse_file_index(html: str) -> list[dict]:
    """
    Parse the "Downloadable Text Files" index page into {label, url} pairs.

    Confirmed structure: <a class="downloadlink" href="...">Label Text</a>.
    Includes every listed file, in scope or not — callers filter via
    mappers.is_in_scope_file.
    """
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for link in soup.select("a.downloadlink"):
        url = link.get("href", "").strip()
        label = link.get_text(strip=True)
        if url and label:
            files.append({"label": label, "url": url})
    return files
