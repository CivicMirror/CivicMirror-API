from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
from typing import Optional


@dataclass
class ResultRow:
    """Normalized result row from a state adapter."""

    candidate_name: Optional[str]
    option_label: Optional[str]
    vote_count: int
    vote_pct: Optional[float]
    is_winner: Optional[bool]
    result_type: str
    office_title: Optional[str] = None
    is_write_in_aggregate: bool = False
    round_number: Optional[int] = None
    jurisdiction_fragment: str = ''
    raw: dict = field(default_factory=dict)


@dataclass
class AdapterResult:
    rows: list[ResultRow]
    source_url: str
    mapping_confidence: str
    notes: str = ''
    # Set by adapter when the upstream version is unchanged from the cached value.
    # The task must NOT write to the version cache when unchanged=True.
    unchanged: bool = False
    # The upstream version string fetched this run (e.g. Clarity "371599").
    # The task should write this to cache AFTER successful DB processing.
    source_version: str = ''


class StateResultsAdapter(ABC):
    state: str

    @abstractmethod
    def fetch_results(self, election_date: datetime.date, election_id: int) -> AdapterResult:
        """Fetch and normalize official results for the given election."""
        raise NotImplementedError
