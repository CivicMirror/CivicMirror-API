"""
Georgia results adapter using the Enhanced Voting ENR API.

Georgia self-hosts the Enhanced Voting platform at results.sos.ga.gov —
same API shape as VA ELECT and WA VoteWA, different base URL.

Election slugs follow MMDDYYYY{ElectionType} (e.g. "11032026General").
Set election.source_metadata = {"enr_slug": "11032026General"} in Django admin.

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
