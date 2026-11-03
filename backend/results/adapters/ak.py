"""
Alaska ENR precinct-results adapter.

Replaces the previous `AlaskaAdapter(ClarityAdapter)` stub, which was wrong
by construction: Alaska does not run Clarity Elections (verified live —
`www.elections.alaska.gov/election-results/` contains zero occurrences of
"clarity"), so `results_url` was always blank and `fetch_results()` returned
before any HTTP request was ever made. See issue #233.

Alaska runs its own Election Night Reporting (ENR) system and publishes one
statewide precinct-level CSV per election:
    https://www.elections.alaska.gov/enr/{yy}{GENR|PRIM}/results/GA_ENR_Precinct_State_of_Alaska.csv
(verified live; `26PRI`/`PR_ENR_...` variants probed and 404). One row per
(precinct, contest, candidate) across ~444 precincts — this adapter sums
them into one statewide row per (contest, candidate).

TLS: www.elections.alaska.gov sends only its leaf certificate during the
handshake, omitting the GlobalSign intermediate that chains it to a trusted
root — a server misconfiguration on Alaska's end (verified live: the
runtime's CA bundle has the current GlobalSign roots; the gap is the
intermediate, not the root). Browsers paper over this by chasing the leaf's
AIA "CA Issuers" URL; requests/urllib3 don't do that automatically, so
verification fails with "unable to get local issuer certificate". Same class
of issue already fixed for AL SOS (#132, see integrations/al_sos/client.py)
— fixed the same way here: pin the missing intermediate (fetched from the
leaf's own AIA URL) and mount an HTTPAdapter that trusts it, keeping
verification on rather than disabling it.

Scope: candidate races only (U.S. Senate/House, Governor/Lt. Governor, State
House/Senate). Ballot measures and judicial retentions are excluded —
every such contest's only two "candidates" are literally named YES and NO
(verified against the live Nov 2026 general file: 23/23 non-candidate
contests, no false positives), so filtering on
`candidate_name.strip().upper() in {"YES", "NO"}` is exact and needs no
office-title keyword list.

No ETag/Last-Modified is served, so there's no cheap version probe (unlike
Clarity's current_ver.txt) — the full ~3MB CSV is fetched every poll and a
SHA-256 of its bytes stands in for a version string.

Result type is always "unofficial": this is Alaska's live election-night
feed, not a certified canvass, so it carries the same ResultType.UNOFFICIAL
convention as ClarityAdapter and the AZ ENR adapter. That also keeps
derive_winners from ever running automatically on this feed (it requires
ResultType.OFFICIAL) — which matters because every general-election
candidate contest in Alaska is decided by ranked-choice instant runoff, so a
first-choice plurality leader in this feed is not necessarily the winner.
(The primary is a nonpartisan top-four blanket primary, not RCV, but the
same "never auto-derive a winner from this feed" default applies there too.)

Known gaps left for a follow-up, not blocking ingestion:
  - The Governor/Lt. Governor ticket is reported as one combined
    candidate_name ("Bronson/Church") rather than two people — passed
    through as-is.
  - This feed only carries first-choice totals; RCV final-round results (for
    contests that go to additional rounds) are not modeled here.
"""
from __future__ import annotations

import hashlib
import io
import logging
import ssl
from collections import defaultdict
from csv import DictReader

import requests
from django.core.cache import cache
from requests.adapters import HTTPAdapter

from elections.models import Election
from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CSV_HOST = "www.elections.alaska.gov"
_CSV_URL_TEMPLATE = (
    f"https://{_CSV_HOST}/enr/{{yy}}{{suffix}}/results/GA_ENR_Precinct_State_of_Alaska.csv"
)

# AK ENR's URL only follows this {yy}{suffix} shape for these two election
# types (verified live) — never guess a suffix for anything else.
_ELECTION_TYPE_SUFFIX: dict[str, str] = {
    Election.ElectionType.GENERAL: "GENR",
    Election.ElectionType.PRIMARY: "PRIM",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_FETCH_TIMEOUT = 60

# Ballot-measure and judicial-retention contests present their only two
# "candidates" as a bare YES/NO vote — verified 23/23 live, no false
# positives. No in-scope candidate race uses these as a candidate name.
_YES_NO = frozenset({"YES", "NO"})

# www.elections.alaska.gov omits its GlobalSign GCC R46 OV TLS CA 2025
# intermediate during the TLS handshake (a server misconfiguration, verified
# live 2026-11-03 — see module docstring and issue #233). Fixed by pinning
# the missing intermediate so `requests` can complete the chain itself.
#
# Fetched 2026-11-03 via the leaf's own AIA "CA Issuers" URL
# (http://secure.globalsign.com/cacert/gsgccr46ovtlsca2025.crt).
# Re-fetch and replace if Alaska rotates certs and the TLS errors return —
# this intermediate expires 2029-06-23; the leaf serving it expires
# 2027-04-24.
_MISSING_INTERMEDIATE_CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIIFfDCCA2SgAwIBAgIRAIRDWJCDb2c5QYLLnJpdyZ8wDQYJKoZIhvcNAQELBQAw
RjELMAkGA1UEBhMCQkUxGTAXBgNVBAoTEEdsb2JhbFNpZ24gbnYtc2ExHDAaBgNV
BAMTE0dsb2JhbFNpZ24gUm9vdCBSNDYwHhcNMjUwOTE3MDI1NTU2WhcNMjkwNjIz
MDAwMDAwWjBUMQswCQYDVQQGEwJCRTEZMBcGA1UEChMQR2xvYmFsU2lnbiBudi1z
YTEqMCgGA1UEAxMhR2xvYmFsU2lnbiBHQ0MgUjQ2IE9WIFRMUyBDQSAyMDI1MIIB
IjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1JyrGiv+210Lw4LTp9qxx9WC
o6w8HnxcTKr5XwR6WwtKidGXriLqGXtBINGTi4HUZ1Vl3FUIvscLwNcq2DRLwjWs
cYFNClVnuSw4CtwAcfa7Iltz+0FmFeh/KOWv5BfgCxAo9FaeXRG725b2eedo/7fb
0zBc6M/XcfQREVteZ6GovnLE96+T8RzRImvX38Y8vZoulp/XWv3p09C1pgp/53+1
itDl7xbrM4sglGNkeJ5LBN2dOR1sqWCMZ/V4a4cPQwopBtZis1vVh7/k4S6Ysgk0
CTi5vei0RSEIhxoFk48BHSXzTA4FJxqjfauYCZ4M5tmZ/R5VgXOZ4Ck/PifnXQID
AQABo4IBVTCCAVEwDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoGCCsGAQUFBwMB
MBIGA1UdEwEB/wQIMAYBAf8CAQAwHQYDVR0OBBYEFGl0Pq/DWwGVSe4UQVqT+rEw
mNqiMB8GA1UdIwQYMBaAFANcq3OBh6jMsKbVlOI2lkn/BZksMHsGCCsGAQUFBwEB
BG8wbTAuBggrBgEFBQcwAYYiaHR0cDovL29jc3AuZ2xvYmFsc2lnbi5jb20vcm9v
dHI0NjA7BggrBgEFBQcwAoYvaHR0cDovL3NlY3VyZS5nbG9iYWxzaWduLmNvbS9j
YWNlcnQvcm9vdHI0Ni5jcnQwNgYDVR0fBC8wLTAroCmgJ4YlaHR0cDovL2NybC5n
bG9iYWxzaWduLmNvbS9yb290cjQ2LmNybDAhBgNVHSAEGjAYMAgGBmeBDAECAjAM
BgorBgEEAaAyCgECMA0GCSqGSIb3DQEBCwUAA4ICAQBEUTiKxe5jEintARUvLBm9
qWZtGiOSV9E+3bntbFFBDBAroqwB6Cj53Zp/W08HwgxaPXdkVaRNYHB/eAatEtSm
1ldtoorfPc+mVlzbwCwfbpIs2uqW5rF78ne37qy2o+iVnJptq9AzPnlC03+zhhB9
JwmjUXVtPuqQZ96tFl0fAT77xGSLzCO8yfEDrxCqdWz2wneShSbCCsC15JB07OgO
StE+MsVBkwe5+PNzAlAr8NZ6f8mzeY/FzaBzlhYw5+c1yyzXJqp+gjRXWrLpD3Ho
hGOvIXIvCBnyVrYI/HPe6DR5w7oteui9Rt0xfUUudaTkt0iz7fc23eGboZ+bpvgT
gbd/kYK6JOrxawMyfBYxrR5zDHIJX0Mws99DNgACKBUfFadKAfwFw0+0airY5WAI
Xs8yhCb5XGwyzVpcB30BrQbWtqdI0PoE9usNvNbH3YFGfuS8oRmAJEgUUQnwOoGK
jMWtHacw0n8QESdRM274LJvLd9nwawYU4svJpf06FtKPqGH3nXefL741NO9KzDAG
PM11YScyJVfYdBDXFM86HU1fBGTKlkLcG/qMJxOqppY4wydRI3koSH6A78nO2QaJ
yqjTOQyCNHaSlmGjdiOvhJ8y1PiazHnuvWBx6z+7JJF2ukqqfjlSARwyfkfnRUIY
la7ZYEqcc56eoPAiElhvrg==
-----END CERTIFICATE-----
"""


class _AlaskaChainFixAdapter(HTTPAdapter):
    """HTTPAdapter whose SSL context trusts the default CAs plus the
    GlobalSign intermediate Alaska's server fails to send (see module
    docstring and #233)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata=_MISSING_INTERMEDIATE_CERT_PEM)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _build_session() -> requests.Session:
    """A requests.Session with the chain-fix adapter mounted for
    www.elections.alaska.gov only, so a real cert problem on any other host
    this adapter might one day talk to wouldn't get masked."""
    session = requests.Session()
    session.mount(f"https://{_CSV_HOST}", _AlaskaChainFixAdapter())
    return session


def _reverse_name(raw_name: str) -> str:
    """"Last, First Middle Suffix" -> "First Middle Suffix Last" — same
    reversal convention as integrations.az_sos.mappers.normalize_candidate_name.
    Best-effort: suffixes land after the first name, not after the last."""
    name = raw_name.strip()
    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
    return name


def _office_title(contest_title: str) -> str:
    """
    Rename AK's bare "Senate District X" / "House District N" contest titles
    to the "State Senate/House - District" convention used elsewhere
    (integrations.al_sos/mi_sos/pa_sos mappers), so
    results.winners.is_single_seat_office() and
    elections.geography.infer_geography_scope() recognize them. Every other
    AK contest title ("U.S. Senator", "U.S. Representative", "Governor /
    Lieutenant Governor") already matches those regexes unchanged.
    """
    title = " ".join(contest_title.split())
    if title.startswith("Senate District "):
        return f"State Senate - District {title.removeprefix('Senate District ')}"
    if title.startswith("House District "):
        return f"State House - District {title.removeprefix('House District ')}"
    return title


@register
class AlaskaAdapter(StateResultsAdapter):
    state = "AK"

    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"ak:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("AlaskaAdapter: election %s not found", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes='election not found',
            )

        suffix = _ELECTION_TYPE_SUFFIX.get(election.election_type)
        if not suffix:
            logger.warning(
                "AlaskaAdapter: unsupported election_type '%s' for election %s; "
                "AK ENR URL shape is only verified for general/primary",
                election.election_type, election_id,
            )
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes=f"unsupported election_type '{election.election_type}'",
            )

        yy = election.election_date.strftime('%y')
        url = _CSV_URL_TEMPLATE.format(yy=yy, suffix=suffix)

        session = _build_session()

        try:
            resp = session.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("AlaskaAdapter: failed to fetch %s for election %s: %s", url, election_id, exc)
            raise

        content = resp.content
        current_ver = hashlib.sha256(content).hexdigest()

        cache_key = self.version_cache_key(election_id)
        cached_ver = cache.get(cache_key)
        if cached_ver == current_ver:
            logger.debug("AlaskaAdapter: version unchanged for election %s", election_id)
            return AdapterResult(
                rows=[], source_url=url, mapping_confidence='full',
                notes='version unchanged', unchanged=True, source_version=current_ver,
            )

        rows = self._parse_csv(content)

        logger.info(
            "AlaskaAdapter: parsed %d rows from %s for election %s",
            len(rows), url, election_id,
        )

        return AdapterResult(
            rows=rows, source_url=url, mapping_confidence='full',
            notes=f"{len(rows)} rows", source_version=current_ver,
        )

    @staticmethod
    def _parse_csv(content: bytes) -> list[ResultRow]:
        text = content.decode('utf-8-sig')
        reader = DictReader(io.StringIO(text))

        # key = (office_title, candidate_name) -> votes summed across ~444 precincts
        totals: dict[tuple[str, str], int] = defaultdict(int)

        for row in reader:
            raw_name = (row.get('candidate_name') or '').strip()
            if not raw_name or raw_name.upper() in _YES_NO:
                continue  # ballot measure / judicial retention — out of scope

            contest_title = (row.get('Contest_title') or '').strip()
            if not contest_title:
                continue

            office_title = _office_title(contest_title)
            candidate_name = _reverse_name(raw_name)
            try:
                votes = int((row.get('total_votes') or '0').replace(',', '').strip() or 0)
            except ValueError:
                votes = 0
            totals[(office_title, candidate_name)] += votes

        return [
            ResultRow(
                candidate_name=candidate_name,
                option_label=None,
                vote_count=vote_count,
                vote_pct=None,
                is_winner=None,
                result_type=OfficialResult.ResultType.UNOFFICIAL,
                office_title=office_title,
            )
            for (office_title, candidate_name), vote_count in totals.items()
        ]
