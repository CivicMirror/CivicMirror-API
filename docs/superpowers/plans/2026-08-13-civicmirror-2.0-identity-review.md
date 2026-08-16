# CivicMirror 2.0 Phase 5: Identity Review

## Scope

Implement the human-review boundary for provisional people, fuzzy candidate
matches, and unresolved result choices without automatic name-based merges or
exposure of protected filing evidence in public output.

## Completed tasks

- [x] Add immutable `IdentityReviewAuditEvent` records.
- [x] Add transactional reviewer transitions with authenticated-reviewer and
      target validation.
- [x] Resolve provisional people only through explicit human actions.
- [x] Record approved links/merges as redirects while preserving source-row
      provenance.
- [x] Add privacy-safe review serializers that redact evidence when a case
      contains protected data.
- [x] Add prioritized Django Admin display and confirm/defer actions.
- [x] Emit creation audit events for ingestion-created review cases.
- [x] Add migration and focused model, workflow, privacy, and persistence tests.

## Guardrails

- Names, addresses, phone numbers, email, party, jurisdiction, and office
  history never authorize a merge by themselves.
- Public serializers never expose protected source-record fields or evidence
  marked as private.
- Audit events are append-only and store only public-safe metadata.
- Civic-Data suggestions remain external suggestions; this phase does not make
  Civic-Data authoritative or submit changes.

## Verification

Run `make verify-v2` and confirm the isolated Compose database applies the new
review migration without creating legacy tables.
