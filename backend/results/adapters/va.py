"""
Virginia results adapter using the Enhanced Voting ENR API.
"""
from __future__ import annotations

# Re-export parsing helpers for backward-compatibility with tests.
from .enhanced_voting import (
    EnhancedVotingAdapter,
    _get_text,
    _parse_ballot_items,
    _safe_float,
    _safe_int,
)
from .registry import register


@register
class VirginiaAdapter(EnhancedVotingAdapter):
    state = "VA"
    state_name = "Virginia"
