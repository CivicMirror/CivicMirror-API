"""
Utah results adapter using the Enhanced Voting ENR API.

Utah self-hosts the Enhanced Voting platform at electionresults.utah.gov —
same API shape as VA ELECT, WA VoteWA, and GA (results.sos.ga.gov),
different base URL. Independently re-verified live 2026-07-21 against
docs/state-research/UT/UT-Election_Research_V3.md: GET .../jurisdictions/Utah,
.../elections/Utah/{slug}, and .../elections/Utah/{slug}/data all match
EnhancedVotingAdapter's existing parsing exactly, field-for-field.

Election slugs (enr_slug) are opaque, case-sensitive, and inconsistently
formatted (e.g. "primary08122025", "Primary06232026", "general11052024") —
discover them from GET .../jurisdictions/Utah's elections[].publicElectionId
for the election matching the target date; do not derive from the date.
One catalog entry ("primary09052023_Demo") is an explicit demo election —
exclude demo/test elections by policy when building a discovery step
(out of scope for this build). Set
election.source_metadata = {"enr_slug": "<publicElectionId>"}.

Confirmed live (2026-07-21, Primary06232026, 12 ballot items, 0/27 ballot
options had a votePercent key) — Utah never sends votePercent, so
ResultRow.vote_pct is always None for this adapter; this is a real,
confirmed data characteristic, not a bug (the field is Optional and the
existing _safe_float(opt.get("votePercent")) already handles a missing
key gracefully by returning None).

Race names carry a party PREFIX ("REP U.S. House District 2"), unlike
GA's party SUFFIX convention ("Governor - Rep") — stored verbatim, same
as GA; cross-source race matching handles normalization downstream.

The research doc documents real data-quality issues in Utah's feed
(top-level ballotsCast/turnout reported as 0 despite real contest votes;
isOfficialResults=false even when signed canvass documents exist) — none
of these affect this adapter, since it only reads per-contest
ballotItems/ballotOptions data and the existing isOfficialResults ->
result_type mapping already treats it as an advisory signal, consistent
with how GA/VA/WA are handled today. Top-level turnout/reporting fields
are not parsed by this adapter at all.
"""
from __future__ import annotations

from .enhanced_voting import EnhancedVotingAdapter
from .registry import register

_UTAH_API_BASE = "https://electionresults.utah.gov/results/public/api"


@register
class UtahAdapter(EnhancedVotingAdapter):
    state = "UT"
    state_name = "Utah"
    base_url = _UTAH_API_BASE
