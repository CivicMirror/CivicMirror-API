"""
Tests for Iowa SOS PDF parsers.
"""
import pytest

from integrations.ia_sos.parsers import (
    parse_calendar_pdf,
    parse_candidate_list_pdf,
    _infer_election_type,
    _build_election_name,
)


# ---------------------------------------------------------------------------
# Minimal synthetic PDF helpers using reportlab or fallback to raw bytes
# ---------------------------------------------------------------------------

def _minimal_pdf_bytes(text: str) -> bytes:
    """
    Build the smallest valid PDF that pdfplumber can extract text from.
    Uses reportlab if available, otherwise falls back to a raw PDF stub that
    pdfplumber will parse as a blank page (empty parse result — used for
    error-path tests).
    """
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        y = 720
        for line in text.splitlines():
            c.drawString(50, y, line)
            y -= 15
            if y < 50:
                c.showPage()
                y = 720
        c.save()
        return buf.getvalue()
    except ImportError:
        # Minimal 1-page PDF stub (page renders empty)
        stub = b"""%PDF-1.4
1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj
2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj
3 0 obj<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer<</Size 4 /Root 1 0 R>>
startxref
190
%%EOF"""
        return stub


# ---------------------------------------------------------------------------
# Calendar parser tests
# ---------------------------------------------------------------------------

class TestParseCalendarPdf:
    def test_empty_bytes_returns_empty_list(self):
        result = parse_calendar_pdf(b"not a pdf")
        assert result == []

    def test_deduplication(self):
        # Two identical entries in same document should collapse to one
        text = (
            "June 2, 2026 Statewide Primary Election\n"
            "June 2, 2026 Statewide Primary Election\n"
        )
        pdf = _minimal_pdf_bytes(text)
        results = parse_calendar_pdf(pdf)
        # With reportlab available, we expect deduplicated results
        dates = [r["election_date"] for r in results]
        assert len(dates) == len(set(dates)) or len(results) <= 1

    def test_invalid_pdf_returns_empty_list(self):
        result = parse_calendar_pdf(b"\x00\x01\x02")
        assert result == []


class TestInferElectionType:
    def test_primary(self):
        assert _infer_election_type("June 2026 Primary Election") == "primary"

    def test_general(self):
        assert _infer_election_type("November General Election 2026") == "general"

    def test_special(self):
        assert _infer_election_type("Special Election for HD-3") == "special"

    def test_municipal(self):
        assert _infer_election_type("City Municipal Election") == "municipal"

    def test_unknown_returns_other(self):
        assert _infer_election_type("Board Meeting March 2026") == "other"


class TestBuildElectionName:
    def test_includes_year(self):
        name = _build_election_name("2026 Primary Election filing deadline", 2026, "primary")
        assert "2026" in name

    def test_fallback_format(self):
        name = _build_election_name("", 2027, "general")
        assert "2027" in name
        assert "General" in name or "general" in name


# ---------------------------------------------------------------------------
# Candidate list parser tests
# ---------------------------------------------------------------------------

class TestParseCandidateListPdf:
    def test_empty_bytes_returns_empty_list(self):
        result = parse_candidate_list_pdf(b"not a pdf")
        assert result == []

    def test_invalid_pdf_returns_empty_list(self):
        result = parse_candidate_list_pdf(b"\x00\x01\x02")
        assert result == []

    def test_returns_list_type(self):
        # Even a blank PDF should return a list
        pdf = _minimal_pdf_bytes("")
        result = parse_candidate_list_pdf(pdf)
        assert isinstance(result, list)

    def test_candidate_row_structure(self):
        """Each returned row must have the expected keys."""
        # Build a minimal table-like PDF with pdfplumber-detectable content
        # This test verifies the output contract when at least one row is parsed
        try:
            from io import BytesIO
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter

            buf = BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)
            # Simple text layout that resembles a candidate list
            c.drawString(50, 750, "Office          Candidate Name         Party  District")
            c.drawString(50, 730, "Governor        Jane Smith             DEM    Statewide")
            c.drawString(50, 710, "Governor        Bob Jones              REP    Statewide")
            c.save()
            pdf_bytes = buf.getvalue()
        except ImportError:
            pytest.skip("reportlab not installed — skipping full parse test")

        results = parse_candidate_list_pdf(pdf_bytes)
        for row in results:
            assert "office" in row
            assert "candidate_name" in row
            assert "party" in row
            assert "district" in row
