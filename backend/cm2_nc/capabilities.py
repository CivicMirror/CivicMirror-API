from datetime import date

from cm2_ingestion.capabilities import StateCapabilities

from .sources.candidate_filings import NcCandidateFilingsSource
from .sources.results import NcResultsZipSource
from .sources.upcoming_elections import NcUpcomingElectionsSource


def build_nc_capabilities(*, results_election_date: date | None = None) -> StateCapabilities:
    return StateCapabilities(
        election_discovery=NcUpcomingElectionsSource(),
        candidates=NcCandidateFilingsSource(),
        results=NcResultsZipSource(election_date=results_election_date) if results_election_date else None,
    )
