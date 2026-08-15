from cm2_ingestion.capabilities import StateCapabilities

from .sources.candidate_filings import NcCandidateFilingsSource
from .sources.upcoming_elections import NcUpcomingElectionsSource


def build_nc_capabilities() -> StateCapabilities:
    return StateCapabilities(
        election_discovery=NcUpcomingElectionsSource(),
        candidates=NcCandidateFilingsSource(),
    )
