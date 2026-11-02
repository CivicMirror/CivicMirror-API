# NC election classification implementation contract

Approved direction: jurisdiction first; current statutory/official regular calendar; UNEXPIRED/title or TRUE filing flags permit inferred special context; municipal November defaults to inferred general. Municipality-specific dates remain follow-up. Existing historical identity holds remain untouched.

## Representation

Classification is stored in source_metadata.nc_classification, schema version 1, and exposed as classification on Elections and races. Independent fields are jurisdiction (kind/key/name), phase, special_context, evidence_status (confirmed/inferred/held), reasons, sources, rule_version, and research_status. Public election_type projects nomination phases to primary/primary_runoff, ordinary state/county decisions to general/general_runoff, special decisions to special, and municipal decisions to municipal. No classification alone certifies results or selects winners.

## Events

Regular federal/state/judicial contests share the regular state election date; their actual district jurisdiction stays on the race. Ordinary county and municipal events are separately jurisdiction-qualified. Special events additionally qualify by normalized office/district to preserve independent vacancies. Evidence status never appears in identity. Existing regular state keys stay compatible with other writers. Legacy parent records with remaining held races persist as review containers; empty split parents are retired with replacement IDs and excluded from ordinary election lists.

## Sources and exceptions

Use exact known regular primary dates for audited historical years and current statutory March/November dates for future cycles, plus explicit scoped exceptions from the inventory. November municipal contests without specific overrides are inferred general; non-November municipal phases remain held pending the announced follow-up, except explicitly sourced events already audited. Dated overrides carry source URLs and do not apply beyond their scope. Do not infer a runoff merely because a date is reserved for it. For old files use legacy CSV parsing without fabricated contest-group IDs.

## Ingestion and repair

Discovery seeds regular state calendar dates without needing results. Candidate sync resolves events instead of selecting one Election per date. Result routing filters before bootstrap and includes classification/routing version in cache validity. CSV hints preserved on races support context that results titles omit. A mixed parent with held legacy races cannot receive unfiltered date results. Legacy unclassified test/data records retain compatibility until explicitly reconciled.

Repair is separate, default dry-run, based on current filing and results bytes plus a complete relationship snapshot. Reparent/rekey supported races without changing candidate/result IDs or values. Preserve superseded rows and previously held identity components. Apply requires an unchanged approved fingerprint inside a transaction; source/report or relation failures roll back. Use the latest live production image as deployment base, with scoped NC files, to preserve the already-deployed KY changes absent from main.
