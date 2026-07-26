from unittest.mock import MagicMock, patch

import pytest


@patch("integrations.ny_boe.client.sync_playwright")
def test_client_discovers_primary_certification_and_skips_offices_to_be_filled(mock_sync_playwright):
    from integrations.ny_boe.client import NyBoeClient

    html = """
    <a href="/cert-primary.pdf">Certification for the June 23, 2026 Primary Election</a>
    <a href="/offices.pdf">Certification of Offices to be Filled - November 2026 General Election</a>
    """
    mock_p = mock_sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.goto.return_value = MagicMock(ok=True, status=200)
    mock_page.content.return_value = html

    docs = NyBoeClient().get_current_certification_documents()

    assert len(docs) == 1
    assert docs[0]["document_type"] == "primary_candidate_certification"
    assert docs[0]["election_date"].isoformat() == "2026-06-23"
    assert docs[0]["pdf_url"] == "https://elections.ny.gov/cert-primary.pdf"


@patch("integrations.ny_boe.client.sync_playwright")
def test_client_discovery_raises_on_blocked_landing_page(mock_sync_playwright):
    from integrations.ny_boe.client import NyBoeClient

    mock_p = mock_sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.goto.return_value = MagicMock(ok=False, status=403)

    with pytest.raises(RuntimeError, match="403"):
        NyBoeClient().get_current_certification_documents()


# ---------------------------------------------------------------------------
# fetch_certification_pdf
#
# elections.ny.gov's WAF 403s an in-page fetch (page.request.get — no
# Sec-Fetch-Mode: navigate) but lets a real top-level navigation through as a
# file download, so Playwright's page.goto() always raises "Download is
# starting" for a PDF URL here — that's the expected control flow, not an
# error, and the real bytes come from the intercepted Download object.
# ---------------------------------------------------------------------------


def _mock_download(mock_sync_playwright, download_path):
    mock_p = mock_sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.goto.side_effect = RuntimeError("Download is starting")
    mock_download = MagicMock()
    mock_download.path.return_value = download_path
    mock_page.expect_download.return_value.__enter__.return_value.value = mock_download
    return mock_page


@patch("integrations.ny_boe.client.sync_playwright")
def test_client_fetch_certification_pdf_validates_magic_bytes(mock_sync_playwright, tmp_path):
    from integrations.ny_boe.client import NyBoeClient

    bad_file = tmp_path / "not-a-pdf.bin"
    bad_file.write_bytes(b"not a pdf")
    _mock_download(mock_sync_playwright, bad_file)

    with pytest.raises(ValueError, match="not a PDF"):
        NyBoeClient().fetch_certification_pdf("https://elections.ny.gov/cert.pdf")


@patch("integrations.ny_boe.client.sync_playwright")
def test_client_fetch_certification_pdf_raises_when_download_never_lands(mock_sync_playwright):
    from integrations.ny_boe.client import NyBoeClient

    mock_page = _mock_download(mock_sync_playwright, None)

    with pytest.raises(RuntimeError, match="download failed"):
        NyBoeClient().fetch_certification_pdf("https://elections.ny.gov/cert.pdf")
    assert mock_page.expect_download.called


@patch("integrations.ny_boe.client.sync_playwright")
def test_client_fetch_certification_pdf_accepts_valid_pdf(mock_sync_playwright, tmp_path):
    from integrations.ny_boe.client import NyBoeClient

    pdf_file = tmp_path / "cert.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 ...")
    _mock_download(mock_sync_playwright, pdf_file)

    content = NyBoeClient().fetch_certification_pdf("https://elections.ny.gov/cert.pdf")

    assert content == b"%PDF-1.4 ..."
