from __future__ import annotations

import base64
import ssl
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .exceptions import AlSosError, AlSosRetryableError

_BASE_URL = "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx"
_FCPA_BASE_URL = "https://fcpa.alabamavotes.gov/page.request.do"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_REQUIRED_FIELDS = ("__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR")

# www.sos.alabama.gov and fcpa.alabamavotes.gov (but not www2.alabamavotes.gov)
# send only their leaf certificate during the TLS handshake, omitting their
# GlobalSign Atlas intermediate CA -- a server misconfiguration on Alabama's
# end, not a local trust-store gap (verified live 2026-08-02: the runtime's CA
# bundle has every current GlobalSign root; browsers paper over this by
# chasing the leaf's AIA "CA Issuers" URL, which requests/urllib3 don't do).
# Fixed by pinning the two missing intermediates so `requests` can complete
# the chain itself. See issue #132.
#
# Fetched 2026-08-02 via each host's own AIA "CA Issuers" URL
# (http://secure.globalsign.com/cacert/gsatlasr3ovtls{ca2026q1,ca2025q3}.crt).
# Re-fetch and replace if Alabama rotates certs and the SSL errors return —
# sos.alabama.gov's expires 2027-10-15, fcpa.alabamavotes.gov's 2027-04-16.
_MISSING_INTERMEDIATE_CERTS_PEM = """\
-----BEGIN CERTIFICATE-----
MIIEkDCCA3igAwIBAgIRAIRx9E+fk3iGs/qiMHFMX8AwDQYJKoZIhvcNAQELBQAw
TDEgMB4GA1UECxMXR2xvYmFsU2lnbiBSb290IENBIC0gUjMxEzARBgNVBAoTCkds
b2JhbFNpZ24xEzARBgNVBAMTCkdsb2JhbFNpZ24wHhcNMjUxMDE1MDMxMDAyWhcN
MjcxMDE1MDAwMDAwWjBYMQswCQYDVQQGEwJCRTEZMBcGA1UEChMQR2xvYmFsU2ln
biBudi1zYTEuMCwGA1UEAxMlR2xvYmFsU2lnbiBBdGxhcyBSMyBPViBUTFMgQ0Eg
MjAyNiBRMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAKCVPu0JMF+1
35y1LrJ0PUvo82n9xrVVBRQjmGkypkTa1UIIMwq2GbU96aVVfAAMdpleyWBHp9Oo
Oa2WGtfEXY0gljHvesO2e8/6ahvLiwORRqQyHFsuXGDrfVWpLm8tpdNiE8q4HCix
V5K8FCKeSm2v2Aq5jefl+OJe7TPyBdPn4sKxa+fWCDWVm8QGM/7HU1U69U5lkrx4
ixDBRhuW+JOFnwcxzBMZ+RHf8TFN5Qu+2xM1v2R+bv3IvkAY4sltTQgewUAoDCQz
eI2KrvmpiHnoEVDGKg3KYaEdNuacooReoh0hefIbgQcpzIuVFd//FQEE0P2LfY23
KIacb4UPWbECAwEAAaOCAV8wggFbMA4GA1UdDwEB/wQEAwIBhjAdBgNVHSUEFjAU
BggrBgEFBQcDAQYIKwYBBQUHAwIwEgYDVR0TAQH/BAgwBgEB/wIBADAdBgNVHQ4E
FgQU6sS1/o6Nampvo+vxuixa/NrtVWwwHwYDVR0jBBgwFoAUj/BLf6guRSSuTVD6
Y5qL3uLdG7wwewYIKwYBBQUHAQEEbzBtMC4GCCsGAQUFBzABhiJodHRwOi8vb2Nz
cDIuZ2xvYmFsc2lnbi5jb20vcm9vdHIzMDsGCCsGAQUFBzAChi9odHRwOi8vc2Vj
dXJlLmdsb2JhbHNpZ24uY29tL2NhY2VydC9yb290LXIzLmNydDA2BgNVHR8ELzAt
MCugKaAnhiVodHRwOi8vY3JsLmdsb2JhbHNpZ24uY29tL3Jvb3QtcjMuY3JsMCEG
A1UdIAQaMBgwCAYGZ4EMAQICMAwGCisGAQQBoDIKAQIwDQYJKoZIhvcNAQELBQAD
ggEBADtC+KuzEXDbnznM+RmF4MboUNmR8QWb706EmWMHVQgyp4VRoDGQk4YZlP7k
4nr7bVmROuie/jviszRTUjdWGzQFMwcLmg/MZ6qhar+9TpoDTRlefo75jZgwX/HK
loryPkNOct+1UKY9E/b6lVi/KOqX4Ims4n0fx6t5XMmGk2RcwcErCk+d4n4kwqz6
5LVvYw6K4cbu2VICfB32y61Vb0+87WKKO43szT+ybe9XC84lFj9bLSzV9ngXC1TR
XtFvuSsi3CaWUSGacPh0u5yCZebBnoHinM21zhrERKt/K/LMYCWgYq1Rz7Xf/8D+
UG0mQv9ZD87UhKb/2UhKjmtkXjE=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIEkDCCA3igAwIBAgIRAINDHIv6TvHHkwd6mdGHshQwDQYJKoZIhvcNAQELBQAw
TDEgMB4GA1UECxMXR2xvYmFsU2lnbiBSb290IENBIC0gUjMxEzARBgNVBAoTCkds
b2JhbFNpZ24xEzARBgNVBAMTCkdsb2JhbFNpZ24wHhcNMjUwNDE2MDMxNTAzWhcN
MjcwNDE2MDAwMDAwWjBYMQswCQYDVQQGEwJCRTEZMBcGA1UEChMQR2xvYmFsU2ln
biBudi1zYTEuMCwGA1UEAxMlR2xvYmFsU2lnbiBBdGxhcyBSMyBPViBUTFMgQ0Eg
MjAyNSBRMzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAKSgnHRJRj1k
YZ6Z9+SeNA90pLnX6FZ8PNejh5wi+0FbmJu1tSos1P4WBAZkeO2m5RsowlCgDNLR
vDlHtfLJazmlzUQd3qDYHJnBGQXkTKmoc7A1B1DXQh7rrONxIVY+yosjZLB57KLr
QknDKyzN2a64KyqdVitSojrmrZUtsubeU2E2MVRTBs+5bo5NBsLKQUBUrtOI6S8V
dZAQm/kpTTkQIOtYsPC6yfTOZx7s4jJXrzJoik42+NDW66P+U8Wr4BpVG8Q5QkRV
B7uQgLP96DzHoM4yuy43IvH2TfRhkd+f/2DOpYzjmJNu6EsNaqhohtW9tqY4YbDn
VNjxa8Vi8jkCAwEAAaOCAV8wggFbMA4GA1UdDwEB/wQEAwIBhjAdBgNVHSUEFjAU
BggrBgEFBQcDAQYIKwYBBQUHAwIwEgYDVR0TAQH/BAgwBgEB/wIBADAdBgNVHQ4E
FgQUXEjtqfv6es9uoq2VL8ZqnR+zGBYwHwYDVR0jBBgwFoAUj/BLf6guRSSuTVD6
Y5qL3uLdG7wwewYIKwYBBQUHAQEEbzBtMC4GCCsGAQUFBzABhiJodHRwOi8vb2Nz
cDIuZ2xvYmFsc2lnbi5jb20vcm9vdHIzMDsGCCsGAQUFBzAChi9odHRwOi8vc2Vj
dXJlLmdsb2JhbHNpZ24uY29tL2NhY2VydC9yb290LXIzLmNydDA2BgNVHR8ELzAt
MCugKaAnhiVodHRwOi8vY3JsLmdsb2JhbHNpZ24uY29tL3Jvb3QtcjMuY3JsMCEG
A1UdIAQaMBgwCAYGZ4EMAQICMAwGCisGAQQBoDIKAQIwDQYJKoZIhvcNAQELBQAD
ggEBAFY1EA5KwC1jogCx3zN7c2AMAe6XDTYBRRsR59XHSylYuN6YLEREWo07fxQ2
zFiU/otJSQgANW0gKDZojZpOZehaCdqshHUlFmLAwV4hIVAJ/F6/YS8KIFjuJdqb
6I1w5TaZ5G2qUy09x4oNDCThm5sZPNvG/9qznPXKxxeuDnz+XMJDrpQN+12ArhKS
XBWh/J4T2CJtHaES3PNIhuhxS6hwkpmg+GfEKAEp6x6ctqZTGFL1TurSme9AqFkC
jKWKc6wvWtefDecrILveOPHbYzvix0tih8A6vYGIxU04v5Jys0mli2K5TNtXFIcn
fwHqPtKzIkdI3ZePcb7vHAz2uI4=
-----END CERTIFICATE-----
"""


class _AlabamaChainFixAdapter(HTTPAdapter):
    """HTTPAdapter whose SSL context trusts the default CAs plus the two
    intermediates Alabama's servers fail to send (see comment above)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata=_MISSING_INTERMEDIATE_CERTS_PEM)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def enr_url_for_ecode(ecode: str) -> str:
    return f"{_BASE_URL}?ecode={ecode.strip()}"


def extract_webforms_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    fields: dict[str, str] = {}
    for name in _REQUIRED_FIELDS:
        node = soup.find("input", id=name)
        value = (node.get("value") if node else None) or ""
        if not value:
            raise AlSosError(f"Alabama ENR page missing {name}")
        fields[name] = value
    return fields


def ecode_from_results_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("ecode") or []
    return values[0].strip() if values else ""


class AlSosClient:
    def __init__(self, session=None, timeout: int = 30, export_timeout: int = 60):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        # Only these two hosts omit their intermediate cert (verified live
        # 2026-08-02) -- www2.alabamavotes.gov (ENR export) chains fine as-is.
        chain_fix_adapter = _AlabamaChainFixAdapter()
        self.session.mount("https://www.sos.alabama.gov", chain_fix_adapter)
        self.session.mount("https://fcpa.alabamavotes.gov", chain_fix_adapter)
        self.timeout = timeout
        self.export_timeout = export_timeout

    def fetch_enr_export(self, ecode: str) -> bytes:
        if not ecode or not ecode.strip():
            raise AlSosError("Alabama ENR ecode is required")
        return self.fetch_enr_export_from_url(enr_url_for_ecode(ecode))

    def fetch_enr_export_from_url(self, url: str) -> bytes:
        try:
            get_response = self.session.get(url, timeout=self.timeout)
            get_response.raise_for_status()
            fields = extract_webforms_fields(get_response.text)
            post_response = self.session.post(
                url,
                data={
                    "__EVENTTARGET": "hlnkExportData",
                    "__EVENTARGUMENT": "",
                    **fields,
                },
                timeout=self.export_timeout,
            )
            post_response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama ENR export request failed: {exc}") from exc

        content_type = post_response.headers.get("Content-Type", "")
        disposition = post_response.headers.get("Content-Disposition", "")
        if "spreadsheetml" not in content_type and "sosEnrExport.xlsx" not in disposition:
            raise AlSosError("Alabama ENR export did not return an Excel workbook")
        return post_response.content

    def fetch_election_year_page(self, year: int) -> str:
        url = f"https://www.sos.alabama.gov/alabama-votes/voter/election-information/{year}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama election-information page request failed: {exc}") from exc
        return response.text

    def fetch_fcpa_race_search(self, election_id: str, office_id: int, page_number: int, page_size: int = 100) -> str:
        params = {
            "page": "com.acf.common.page.politicalracesearchresults",
            "pageNumber": page_number,
            "pageSize": page_size,
            "sortDirection": "ASC",
            "sortBy": "candidate",
            "election": election_id,
            "office": office_id,
            "jurisdiction": "null",
            "party": "null",
            "place": "null",
            "district": "null",
            "city": "null",
            "year": "null",
        }
        url = f"{_FCPA_BASE_URL}?{urlencode(params)}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA race search request failed: {exc}") from exc
        return response.text

    def fetch_fcpa_committee_detail(self, committee_id: int) -> str:
        encoded_type = base64.b64encode(b"pcc").decode()
        encoded_id = base64.b64encode(str(committee_id).encode()).decode()
        params = {
            "page": "page.acfPublicCommitteeDetails",
            "type": encoded_type,
            "id": encoded_id,
        }
        url = f"{_FCPA_BASE_URL}?{urlencode(params)}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA committee detail request failed: {exc}") from exc
        return response.text
