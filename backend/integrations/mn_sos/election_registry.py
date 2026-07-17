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

def _default_status_for_date(election_date: datetime.date) -> str:
    """Infer Election.Status for unpinned MN descriptors without importing Django models."""
    today = datetime.date.today()
    if election_date > today:
        return "upcoming"
    if election_date == today:
        return "active"
    return "results_pending"


@dataclasses.dataclass
class MnElection:
    election_date: datetime.date
    election_type: str
    name: str
    status: str | None = None
    suffix: str | None = None
    ers_election_id: int | None = None
    source_id: str | None = None

    def __post_init__(self):
        if self.status is None:
            self.status = _default_status_for_date(self.election_date)
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
        status=entry.get("status"),
        suffix=str(entry["suffix"]) if entry.get("suffix") is not None else None,
        ers_election_id=entry.get("ers_election_id"),
        source_id=entry.get("source_id"),
    )


def load_elections() -> list[MnElection]:
    """Load the seed MN elections from the bundled TOML file."""
    data = tomllib.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return [_to_descriptor(e) for e in data.get("election", [])]


def _split_date_path(date_path: str) -> tuple[datetime.date, str | None]:
    base, _, suffix = date_path.partition("_")
    return datetime.datetime.strptime(base, "%Y%m%d").date(), (suffix or None)


def _descriptor_from_election(election, source_id: str) -> MnElection:
    meta = election.source_metadata or {}
    _, suffix = _split_date_path(meta["mn_date_path"])
    return MnElection(
        election_date=election.election_date,
        election_type=election.election_type,
        name=election.name,
        status=election.status,
        suffix=suffix,
        ers_election_id=meta.get("mn_ers_election_id"),
        source_id=source_id,
    )


def registered_elections() -> list[MnElection]:
    """
    All MN elections to sync: the bundled TOML seed plus any mn_sos elections
    already registered in the DB (e.g. auto-onboarded by discover_mn_elections),
    deduped by date_path so a pinned seed is never double-processed. Requires DB
    access; the TOML seed always wins a date_path collision.
    """
    from elections.models import ElectionSourceLink  # local import: needs Django

    by_date_path: dict[str, MnElection] = {e.date_path: e for e in load_elections()}
    links = ElectionSourceLink.objects.filter(source="mn_sos").select_related("election")
    for link in links:
        if not (link.election.source_metadata or {}).get("mn_date_path"):
            continue
        descriptor = _descriptor_from_election(link.election, link.source_id)
        by_date_path.setdefault(descriptor.date_path, descriptor)
    return list(by_date_path.values())
