"""
Shared in-scope file discovery for MN SOS Stage 1 (race/candidate sync) and
Stage 2 (results adapter).

Both stages need the same thing: the set of Federal+State result files for one
election. They must also handle the Radware-protected index the same way, so
the logic lives here once rather than being duplicated (and drifting) across
tasks.py and results/adapters/mn.py.
"""
from __future__ import annotations

import logging

from .exceptions import MnSosRetryableError
from .manifests import KNOWN_IN_SCOPE_FILES
from .mappers import is_in_scope_file
from .parsers import parse_file_index

logger = logging.getLogger(__name__)


def discover_in_scope_files(client, ers_election_id: int) -> list[dict]:
    """
    Return the in-scope {label, url} result files for one election.

    Discovery order:
      1. Live "Downloadable Text Files" index. When it loads as real HTML we
         parse it and keep only the in-scope (Federal+State) files.
      2. If the index is unavailable — Radware serves a CAPTCHA page, or the
         request fails retryably — fall back to a verified static manifest for
         this election, when one exists.

    A live index that loads cleanly but lists no in-scope files is treated as a
    genuine empty result (an election with no Federal/State offices) and
    returned as an empty list — never masked by the manifest.

    Raises MnSosRetryableError when the index is blocked and no static manifest
    exists for this election, so the caller retries instead of recording a
    false empty success.
    """
    try:
        index_html = client.fetch_file_index(ers_election_id)
    except MnSosRetryableError:
        manifest = KNOWN_IN_SCOPE_FILES.get(ers_election_id)
        if manifest is None:
            logger.warning(
                "mn_sos.discovery.index_blocked_no_manifest ers_election_id=%s",
                ers_election_id,
            )
            raise
        logger.info(
            "mn_sos.discovery.manifest_fallback ers_election_id=%s count=%d",
            ers_election_id, len(manifest),
        )
        return [dict(entry) for entry in manifest]

    return [f for f in parse_file_index(index_html) if is_in_scope_file(f["label"])]
