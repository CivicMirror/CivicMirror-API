"""
In-scope result-file discovery for MN SOS Stage 1 (race/candidate sync) and
Stage 2 (results adapter).

Discovery probes the unprotected file host directly: for a given election's
date path, HEAD each in-scope filename (from the external dictionary,
data/result_filenames.txt) against
electionresultsfiles.sos.mn.gov/{date_path}/ and keep the ones that exist. The
set that returns 200 IS that election's manifest — discovered live, with no
dependency on the Radware-protected portal index.

A file host that returns 200 for a filename means that office is on the ballot
for this election; a 404 means it is not. An empty result is therefore a valid
answer (an election with no Federal/State offices), not an error.
"""
from __future__ import annotations

import logging

from . import filenames

logger = logging.getLogger(__name__)


def probe_in_scope_files(client, date_path: str) -> list[dict]:
    """
    Return the in-scope {filename, url} result files that exist for one
    election, by probing the file host. Transient host failures raise
    MnSosRetryableError (from the client) so the caller retries.
    """
    found: list[dict] = []
    for name in filenames.in_scope_filenames():
        if client.file_exists(date_path, name):
            found.append({"filename": name, "url": client.file_url(date_path, name)})
    logger.info(
        "mn_sos.discovery.probe date_path=%s found=%d",
        date_path, len(found),
    )
    return found
