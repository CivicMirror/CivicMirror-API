"""
Loader for the external MN SOS result-file dictionary
(data/result_filenames.txt).

The dictionary is a data file, not a hardcoded list, so a newly-observed
filename is a one-line edit with no code change. It is the single source of
truth for both what to probe on the file host and which files are in ingest
scope.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "data" / "result_filenames.txt"

FEDERAL_STATE = "federal-state"
LOCAL = "local"

_SECTION_RE = re.compile(r"^\[(?P<name>[a-z-]+)\]$")


def parse_filename_dictionary(text: str) -> dict[str, list[str]]:
    """Parse the grouped dictionary text into {section: [filenames]}."""
    groups: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        section = _SECTION_RE.match(line)
        if section:
            current = groups.setdefault(section.group("name"), [])
            continue
        if current is not None:
            current.append(line)
    return groups


@functools.lru_cache(maxsize=1)
def load_dictionary() -> dict[str, list[str]]:
    """Load and cache the bundled result-file dictionary."""
    return parse_filename_dictionary(_DATA_FILE.read_text(encoding="utf-8"))


def in_scope_filenames() -> list[str]:
    """Filenames in the current ingest scope (Federal + State offices)."""
    return list(load_dictionary().get(FEDERAL_STATE, []))
