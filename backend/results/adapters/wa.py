"""
Washington results adapter using the Enhanced Voting ENR API (VoteWA).
"""
from __future__ import annotations

from .enhanced_voting import EnhancedVotingAdapter
from .registry import register


@register
class WashingtonAdapter(EnhancedVotingAdapter):
    state = "WA"
    state_name = "washington"
    base_url = "https://results.votewa.gov/results/public/api"
