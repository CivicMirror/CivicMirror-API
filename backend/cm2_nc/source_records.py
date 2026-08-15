from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class NcCandidateRow:
    row_number: int
    election_date: date
    county_name: str
    contest_name: str
    name_on_ballot: str
    first_name: str
    middle_name: str
    last_name: str
    suffix: str
    nickname: str
    protected_address: str
    protected_phone: str
    protected_email: str
    filing_date: date | None
    party_contest: str
    party_candidate: str
    is_unexpired: bool
    has_primary: bool
    is_partisan: bool
    vote_for: int
    term_years: int
