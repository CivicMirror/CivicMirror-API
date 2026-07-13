"""
Scope classification for Minnesota SOS downloadable files.

Federal + State offices only this build (county/municipal/school/hospital,
ballot questions, and district court deferred — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
"""
from __future__ import annotations

import re

IN_SCOPE_LABELS = frozenset({
    "U.S. President Statewide",
    "U.S. Senator Statewide",
    "U.S. Representative by District",
    "State Senator by District",
    "State Representative by District",
    "Supreme Court and Courts of Appeals Races",
})

# No Governor/state executive file exists in the Nov 2024 general (off-year
# for MN's governor); match by pattern for future gubernatorial cycles.
_GOVERNOR_PATTERN = re.compile(r"^Governor.*\bStatewide\b", re.IGNORECASE)

_WRITE_IN_ORDER_CODE = "9901"


def is_in_scope_file(label: str) -> bool:
    if label in IN_SCOPE_LABELS:
        return True
    return bool(_GOVERNOR_PATTERN.match(label.strip()))


def is_write_in(candidate_order_code: str) -> bool:
    return candidate_order_code == _WRITE_IN_ORDER_CODE
