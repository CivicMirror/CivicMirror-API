# NC source-qualified contest identity (#214)

The NC SBE adapter now retains `Contest Group ID`, `Contest Type`, `County`,
`Choice Party`, and `Vote For` in every aggregated row. Aggregation uses the
following source-qualified key:

| Contest type | Aggregation identity |
| --- | --- |
| Statewide/federal/district (`S`) | contest title + contest type + contest group ID + choice |
| County/local (`C`) | contest title + contest type + contest group ID + county + choice |

This preserves one statewide or multi-county contest while preventing same-name,
same-ID county contests from merging. Bootstrap stores the identity in
`Race.source_metadata`; ingest matching requires the same identity fields and
cannot silently fall back to title matching when a source-qualified race exists.

Positive, consistent `Vote For` values become `source_vote_for`. Values greater
than one set `multi_seat` and `max_selections`; a sourced value of one remains
`single_choice` while still retaining its provenance. Zero, missing, or
conflicting values become `source_vote_for_unresolved` and do not establish a
seat count. Candidate party codes are normalized where a candidate has one
unambiguous source value; conflicting values remain blank for review.

This is the identity/metadata foundation only. Existing merged NC races need a
separate dry-run refetch and transactional repair command: stored rows retain
only older contest metadata, so ordinary bootstrap cannot reconstruct their
relationships. That repair must map old to new races, reconcile votes, retire
superseded totals, and preserve source winner flags before any production write.
