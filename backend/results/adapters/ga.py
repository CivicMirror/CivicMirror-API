"""
Georgia results adapter using the Enhanced Voting ENR API.

Georgia self-hosts the Enhanced Voting platform at results.sos.ga.gov —
same API shape as VA ELECT and WA VoteWA, different base URL.

Election slugs are NOT a predictable pattern — GA assigns them by hand per
election (e.g. "GeneralPrimary51926", "06162026GeneralPrimaryRunoff",
"RECOUNTPSCDistrict3"). To find the current slug, fetch
https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia and read
the `elections[].publicElectionId` field for the election matching the
target date — there is no way to derive it from the date alone.
Set election.source_metadata = {"enr_slug": "<publicElectionId>"} in Django
admin (or via the aggregation ingest layer).

Race names include a party suffix ("Governor - Rep", "US Senate - Dem") which
is GA SOS convention for primary/runoff ballots. The results ingest stores
these verbatim; cross-source race matching handles normalisation downstream.
"""
from __future__ import annotations

from .enhanced_voting import EnhancedVotingAdapter
from .registry import register

_GA_API_BASE = "https://results.sos.ga.gov/results/public/api"


@register
class GeorgiaAdapter(EnhancedVotingAdapter):
    state = "GA"
    state_name = "Georgia"
    base_url = _GA_API_BASE
