# Identity Review Glossary

Reference for reviewers working the `cm2_review` admin queue
(`/admin/cm2_review/identityreviewcase/`). Covers case types, resolution actions, and
person identity states — in particular the distinction between **Link existing** and
**Merge people**, which are frequently confused because they currently produce the same
database result.

## Case types

- **New Person** (`person_identity`) — historically created whenever a source record
  couldn't be deterministically matched to any existing `Person` and needed
  confirmation. As of the candidate-filing ingestion path (`cm2_ingestion/persistence.py`),
  this case type is **no longer created** when a brand-new person doesn't resemble any
  existing person at all (`find_person_match_candidates` returns nothing): there is
  nothing for a reviewer to reconcile, so the person is auto-resolved
  (`identity_state → resolved`) at ingestion time instead of sitting in the queue for a
  rubber-stamp "Confirm as distinct person." This is why a large new-state onboarding no
  longer produces thousands of no-op review cases. The result-only write-in path
  (`cm2_ingestion/results_persistence.py::_create_provisional_candidacy`) still creates
  `person_identity` cases for genuinely new provisional people, since that flow has no
  structured name evidence or source record to lean on.
- **Fuzzy person match** (`fuzzy_person_match`) — a provisional `Person` scored close
  enough to one or more existing `Person` records (by name similarity, not deterministic
  identifiers) that a human needs to decide whether they're the same individual. This is
  the only case type candidate-filing ingestion still creates for a brand-new person —
  when `find_person_match_candidates` finds at least one plausible existing match.
- **Unmatched Write-in** (`unresolved_result_choice`) — a reported result choice
  (typically a write-in) couldn't be matched to a candidate on the ballot.

## Resolution actions

| Action | Effect on the provisional `Person` | When to use it |
|---|---|---|
| **Confirm as distinct person** | `identity_state → resolved`, `merged_into` cleared | The provisional person is a real, separate individual — any fuzzy-match suggestions were false positives. |
| **Link existing** | `identity_state → merged`, `merged_into → target person`; source record repointed to target | The new record simply *is* an already-known person (e.g. recognized via a stable identifier or an obvious re-filing) — not really two independently-discovered records converging, more like recognizing someone you already had on file. |
| **Merge people** | Same as Link existing | Two independently-created `Person` records turned out to be the same human (e.g. a fuzzy-match candidate like *William Ray Britton* vs *William Randy Burton*) and are being consolidated. |
| **Defer** | No change | Not enough evidence yet; leaves the case open for a later pass. |
| **Reject** | `identity_state → disputed` | The provisional person's evidence is wrong/unreliable and shouldn't be resolved as-is. |
| **Link Civic-Data** | `identity_state → resolved`, adds a verified `PersonIdentifier` | Attaches an external Civic-Data (or other scheme) identifier to a resolved person, from a review suggestion that carries one. |

### Link existing vs. Merge people

**As implemented today, these two actions are functionally identical.** Both run through
the same branch in `transition_review_case()` (`cm2_review/workflow.py`): the provisional
person is marked `MERGED`, its `merged_into` is set to the chosen target person, and the
source record is repointed to that target. The only difference is which label lands in
`resolution_action` on the audit trail, and the wording of the admin success message.

The distinction exists to record reviewer *intent*, not to change behavior:

- Choose **Link existing** when the review case is really about recognizing that a record
  already belongs to a known person (deterministic-feeling, low ambiguity).
- Choose **Merge people** when you're resolving a genuine fuzzy match between two
  separately created `Person` rows that you've determined represent one real person
  (the common case for `fuzzy_person_match` cases).

If this distinction should ever carry different validation or side effects, that would
need its own change to `workflow.py` — right now, pick whichever label best documents why
you made the call.

## Person identity states

- `provisional` — created by ingestion, not yet reviewed.
- `resolved` — confirmed as its own person (via Confirm as distinct person or Link
  Civic-Data).
- `disputed` — rejected in review; evidence is considered unreliable.
- `merged` — folded into another `Person` via Link existing or Merge people;
  `merged_into` points at the surviving record.
