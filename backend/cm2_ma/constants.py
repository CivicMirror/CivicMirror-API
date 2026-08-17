SOURCE_SYSTEM = "ma_sos"
SEC_BASE_URL = "https://www.sec.state.ma.us"
UPCOMING_ELECTIONS_URL = (
    f"{SEC_BASE_URL}/divisions/elections/recent-updates/upcoming-elections.htm"
)
SPECIAL_ELECTIONS_INDEX_URL = (
    f"{SEC_BASE_URL}/divisions/elections/recent-updates/special-elections.htm"
)

# sec.state.ma.us is Incapsula-blocked; every fetch of it goes through the
# shared cloudflare/cf-solver/ nodriver service (core.cf_solver.CfSolverClient),
# which needs a longer timeout than a plain HTTP GET — solves typically take
# ~25-30s. See docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md.
SOURCE_TIMEOUT_SECONDS = 90
SOLVER_WAIT_SECONDS = 25

UPCOMING_PARSER_VERSION = "ma-upcoming-v1"
SPECIAL_INDEX_PARSER_VERSION = "ma-special-index-v1"
SPECIAL_CALENDAR_PARSER_VERSION = "ma-special-calendar-v1"

OCPF_DISTRICT_CODE_LIST_URL = (
    "https://ocpf2.blob.core.windows.net/downloads/data2/district_code_list.zip"
)
OCPF_FILERS_URL = "https://ocpf2.blob.core.windows.net/downloads/data2/ocpf-filers-excel.zip"
OCPF_DISTRICT_PARSER_VERSION = "ma-ocpf-district-v1"
OCPF_FILERS_PARSER_VERSION = "ma-ocpf-filers-v1"
