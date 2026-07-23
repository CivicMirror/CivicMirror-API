from unittest.mock import MagicMock, patch

import pytest


def test_client_discovers_primary_certification_and_skips_offices_to_be_filled():
    from integrations.ny_boe.client import NyBoeClient

    html = """
    <a href="/cert-primary.pdf">Certification for the June 23, 2026 Primary Election</a>
    <a href="/offices.pdf">Certification of Offices to be Filled - November 2026 General Election</a>
    """
    response = MagicMock(text=html)
    response.raise_for_status.return_value = None

    with patch("integrations.ny_boe.client.requests.get", return_value=response):
        docs = NyBoeClient().get_current_certification_documents()

    assert len(docs) == 1
    assert docs[0]["document_type"] == "primary_candidate_certification"
    assert docs[0]["election_date"].isoformat() == "2026-06-23"
    assert docs[0]["pdf_url"] == "https://elections.ny.gov/cert-primary.pdf"


def test_client_fetch_certification_pdf_validates_magic_bytes():
    from integrations.ny_boe.client import NyBoeClient

    response = MagicMock(content=b"not a pdf")
    response.raise_for_status.return_value = None

    with patch("integrations.ny_boe.client.requests.get", return_value=response):
        with pytest.raises(ValueError, match="not a PDF"):
            NyBoeClient().fetch_certification_pdf("https://elections.ny.gov/cert.pdf")
