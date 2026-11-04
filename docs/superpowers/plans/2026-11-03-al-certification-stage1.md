# Alabama Candidate Certification Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate Alabama election-specific candidate races from official SOS candidate-certification documents and retain auditable document versions.

**Architecture:** Extend `integrations.al_sos` with a secure certification-document fetcher, OCR-backed parser, office mapper, and daily Celery task. The task reads election-scoped document links already stored by `sync_al_elections`, selects the latest relevant certification per party in page order, and upserts party-specific primary races or party-agnostic general races through `aggregation.ingest`. Expose the task through the internal trigger/lock pattern; do not change the external production scheduler in this implementation.

**Tech Stack:** Django, Celery, requests, pdfplumber, Poppler `pdftoppm`, Tesseract OCR, pytest.

**Spec:** `docs/state-research/AL/AL-Election_Research.md`, section 4, “Ballot-Qualified Candidates — SOS Certifications”.

## Global Constraints

- Scrape year-page links; do not synthesize or hardcode certification URLs.
- Treat the latest relevant certification per party as authoritative; preserve source document URL and SHA-256 version.
- Never treat FCPA committee status as ballot qualification.
- County sample-ballot ingestion and local-only contests remain out of scope.
- Fail closed on malformed PDFs or OCR output; do not mark candidates withdrawn when a document cannot be parsed.
- Keep TLS verification enabled and restrict document downloads to Alabama SOS URLs.

## Review Focus

- Scanned PDFs with multi-page office/name tables: exercise row grouping and continuation pages.
- Independent-candidate certificates without tables: exercise office/name pairs.
- Party-specific primaries: assert same-office party candidates produce separate races.
- Amended certificates: assert latest linked version is ingested and its SHA-256 is recorded.
- Invalid or empty PDFs / missing OCR binaries: assert a warning/failure is recorded without changing existing candidates.

---

### Task 1: Certification parser and OCR transport

**Files:**
- Modify: `backend/integrations/al_sos/client.py`
- Modify: `backend/integrations/al_sos/parsers.py`
- Modify: `backend/Dockerfile`
- Test: `backend/integrations/al_sos/tests/test_parsers.py`
- Test: `backend/integrations/al_sos/tests/test_client.py`

**Interfaces:**
- Produce `parse_candidate_certification_pdf(pdf_bytes: bytes, *, party: str, document_label: str, source_url: str, sha256: str) -> list[dict]`.
- Each parsed record contains `office_title`, `candidate_name`, `party`, `document_label`, `source_url`, and `source_sha256`.
- Use `pdftoppm` and `tesseract` subprocesses with bounded pages, input size, and timeouts; accept upright two-column tables, rotated four-column tables, and independent certificate office/name pairs.

- [x] Write failing parser tests for table parsing, continuation rows, independent office/name pairs, and malformed PDF bytes.
- [x] Run those focused tests and confirm expected failures.
- [x] Implement bounded SOS-only fetch and OCR parsing; install `poppler-utils` and `tesseract-ocr` in the runtime image.
- [x] Run focused tests and confirm they pass, including manual OCR runs against representative 2026 SOS PDFs.

### Task 2: Candidate/race mapping, synchronization, and provenance

**Files:**
- Modify: `backend/integrations/al_sos/mappers.py`
- Modify: `backend/integrations/al_sos/tasks.py`
- Test: `backend/integrations/al_sos/tests/test_mappers.py`
- Test: `backend/integrations/al_sos/tests/test_tasks.py`

**Interfaces:**
- Produce `sync_al_certifications(self, year: int | None = None)`.
- Select the last candidate-certification link per party from each election’s `al_document_links`; skip sample ballots and result certifications while allowing amended candidate certifications.
- Store parsed document labels, URLs, hashes, and fetch timestamps on election metadata; store each candidate’s certification reference in candidate metadata without discarding existing FCPA metadata.
- Use `contest_variant="al:<party>"` and set race party/ballot type for primary and runoff elections; use an empty variant for general and special-general elections.
- Upsert only; do not delete records or change candidate status based on omission.

- [x] Write failing tests for election-scoped document selection, latest amendment precedence, separate primary party races, metadata preservation, and idempotent replay.
- [x] Run those focused tests and confirm expected failures.
- [x] Implement mapping and `sync_al_certifications` with `SyncLog` accounting and fail-closed OCR errors.
- [x] Run focused tests and confirm they pass.

### Task 3: Internal trigger and focused regression validation

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/task_locks.py`
- Test: `backend/internal/tests/test_views.py`

- [x] Write a failing authorized-trigger/lock test for the certification task.
- [x] Run it and confirm expected failure.
- [x] Add the protected internal trigger route and daily lock.
- [x] Run focused tests and confirm they pass.
- [x] Run the Alabama integration test modules and `ruff check` for changed Python files.
