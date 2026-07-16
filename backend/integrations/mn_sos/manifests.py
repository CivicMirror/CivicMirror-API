"""
Verified static file manifests for MN SOS elections.

The "Downloadable Text Files" index page (electionresults.sos.mn.gov) sits
behind Radware and intermittently answers automated clients with a CAPTCHA
page instead of the real index (see client.fetch_file_index /
discovery.discover_in_scope_files). The actual result files live on the
separate, unprotected electionresultsfiles.sos.mn.gov host, so once an
election's in-scope filenames are known we can fetch them directly and skip
the protected index entirely.

Each manifest below is transcribed verbatim from a real captured index
(label text + href), so it matches exactly what parse_file_index would have
returned for that election. Keyed by ersElectionId.
"""
from __future__ import annotations

_FILE_HOST = "https://electionresultsfiles.sos.mn.gov"

# ersElectionId=170 — Nov 5, 2024 Minnesota general election (date path
# 20241105). Captured 2026-07-16; the six Federal+State in-scope files
# (matching mappers.IN_SCOPE_LABELS).
KNOWN_IN_SCOPE_FILES: dict[int, list[dict]] = {
    170: [
        {"label": "U.S. President Statewide", "url": f"{_FILE_HOST}/20241105/USPres.txt"},
        {"label": "U.S. Senator Statewide", "url": f"{_FILE_HOST}/20241105/ussenate.txt"},
        {"label": "U.S. Representative by District", "url": f"{_FILE_HOST}/20241105/ushouse.txt"},
        {"label": "State Senator by District", "url": f"{_FILE_HOST}/20241105/stsenate.txt"},
        {"label": "State Representative by District", "url": f"{_FILE_HOST}/20241105/LegislativeByDistrict.txt"},
        {"label": "Supreme Court and Courts of Appeals Races", "url": f"{_FILE_HOST}/20241105/judicial.txt"},
    ],
}
