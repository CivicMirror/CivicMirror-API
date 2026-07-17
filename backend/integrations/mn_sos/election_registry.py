"""
Registry of MN SOS elections to sync.

The elections to ingest come from an external data file (data/elections.toml)
rather than being hardcoded, so onboarding an election is a data edit. Each
entry becomes an MnElection descriptor; the sync task iterates them.

date_path is derived from the election date plus an optional same-day-special
suffix (see issue #55). ers_election_id is optional metadata only — discovery
keys on date_path, not the portal id.
"""
from __future__ import annotations

import dataclasses
import datetime
import tomllib
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "data" / "elections.toml"

# Election.Status.UPCOMING; kept as a literal so this data loader needs no
# Django model import.
_DEFAULT_STATUS = "upcoming"


@dataclasses.dataclass
class MnElection:
    election_date: datetime.date
    election_type: str
    name: str
    status: str = _DEFAULT_STATUS
    suffix: str | None = None
    ers_election_id: int | None = None
    source_id: str | None = None

    def __post_init__(self):
        if not self.source_id:
            self.source_id = f"mn_sos_{self.date_path}"

    @property
    def date_path(self) -> str:
        base = self.election_date.strftime("%Y%m%d")
        return f"{base}_{self.suffix}" if self.suffix else base


def _to_descriptor(entry: dict) -> MnElection:
    return MnElection(
        election_date=entry["date"],
        election_type=entry["type"],
        name=entry["name"],
        status=entry.get("status", _DEFAULT_STATUS),
        suffix=str(entry["suffix"]) if entry.get("suffix") is not None else None,
        ers_election_id=entry.get("ers_election_id"),
        source_id=entry.get("source_id"),
    )


def load_elections() -> list[MnElection]:
    """Load the registered MN elections from the bundled TOML file."""
    data = tomllib.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return [_to_descriptor(e) for e in data.get("election", [])]
