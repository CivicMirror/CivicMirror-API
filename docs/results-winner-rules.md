# Derived candidate winners

`results.winners` supplies conservative candidate outcomes when certified contest
totals have no source outcome. Source `True` and `False` flags take priority.
Ballot-measure outcomes remain outside this path (#217).

## Ownership and corrections

Ingestion locks each race and writes its results, certification status, source
takeover, and derivation in one transaction. Before the first matched source
outcome is saved, it clears previously derived aggregate flags and removes
`source_metadata.winners_derived`. Later source flags in the same import are
preserved, including partial imports and explicit `False`. Failed imports roll
back the entire race. Corrections without source outcomes recompute derived
winners. The backfill command also locks and reloads each race before applying,
so a prefetched snapshot cannot overwrite a concurrent source correction.

## Supported primary rules

These are deliberately bounded rules for the data currently under repair, not
a complete US election-law engine. Non-NC rules are enabled for elections from
2026 onward; earlier years require historical verification. NC support starts
with the 2014 archive being repaired. Unknown jurisdictions and rules stay null.

| State / election | Rule | Official evidence |
| --- | --- | --- |
| NC first primary, 2014–2017 | Each winning candidate must strictly exceed 40% of total candidate votes divided by seats | [2017 Session Law 214, sections 3 and 5](https://www.ncleg.gov/EnactedLegislation/SessionLaws/HTML/2017-2018/SL2017-214.html) |
| NC first primary, from 2018-01-01 | Same calculation with a strict 30% threshold | [G.S. 163-111](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByArticle/Chapter_163/Article_10.html) and the effective date in Session Law 214 |
| GA first primary, one seat | Strictly more than 50% | [Georgia primary runoff explanation](https://georgia.gov/events/2026-06-16/general-primary-runoff-election-day) |
| NC / GA primary runoff, one seat, at most two candidates per party | Highest vote count, no tie | G.S. 163-111 and Georgia's runoff explanation above |
| MA first primary | Highest vote counts for available nominations; ties unresolved | [Chapter 53 section 1](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleVIII/Chapter53/Section1), [section 53](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleVIII/Chapter53/Section53) |
| PA first primary | Party plurality, excluding presidential preference | [Election Code section 808](https://www.legis.state.pa.us/WU01/LI/LI/US/HTM/1937/0/0320..HTM) |
| CT first primary | Greatest votes for the party nomination | [Chapter 153, section 9-423](https://www.cga.ct.gov/current/pub/chap_153.htm) |
| MO first primary | Greatest votes for party nomination | [RSMo 115.343](https://www.revisor.mo.gov/main/OneSection.aspx?bid=6100&section=115.343) |
| TN first primary | Highest votes for each available nomination | [Williamson County Election Commission candidate FAQ](https://www.williamsoncounty-tn.gov/2136/Candidate-FAQ) |

NC candidates below the threshold are **not** marked nominated merely because
they lead. Counts do not establish whether a second primary was requested or
waived. NC elections classified as `special` or municipal also remain unknown
pending #188's classification work. GA multi-seat primaries and multi-seat
runoffs have no supported rule here.

Party aliases use `aggregation.identity.normalize_party`. Missing or conflicting
party metadata prevents derivation; nonpartisan, independent, unrecognized
party labels, presidential preference contests, delegates, and top-two states
are unsupported. A named write-in winner requires eligibility/acceptance
evidence not supplied by the current model. In a supported plurality primary,
scattered write-ins can be ignored only when their combined total is strictly
below every party's last winning candidate; otherwise the outcome is unknown.
Threshold primaries with positive scattered write-ins remain unsupported.

## Massachusetts Governor's Council

[Constitution Amendment XVI](https://malegislature.gov/Laws/Constitution) provides
eight districts electing one councillor each. Recognition is limited to MA,
the exact office title, `ma_sos`, district scope, districts 1st through 8th,
and matching ElectionStats/contest identifiers. `single_choice` and
`max_selections=1` remain unchanged. This does not infer seats for other councils
or boards (#216).

## Read-only preflight, 2026-10-05

Exported public race/candidate/result fields in a PostgreSQL read-only
transaction, then evaluated the branch's pure `derive_winners(race, rows)`
locally without applying results. Current data had 1,845 derived races:
NC 1,633, TN 126, PA 76, AL 10. Of these, 1,820 retain their winners;
25 NC races classified `special` would lose derived flags until their election
classification is resolved. This snapshot differs from the earlier issue audit
because scheduled imports continue; counts are not deployment guarantees.

All 12 previously seat-blocked MA Council contests now have one-seat eligibility.
The four additional Council contests have no named candidate totals and remain
`skipped_no_totals`. Ten of the 12 derive winners. Two Republican contests remain
unknown because aggregate write-ins exceed the named leader: district 1st,
race 55828 (1,212 write-ins vs 455 named votes), and district 5th, race 55832
(1,625 vs 1,216). These require source outcomes or resolved write-in eligibility.

| MA race IDs | Outcome |
| --- | --- |
| 55577, 55578, 55579, 55580, 55581, 55582, 55583, 55584, 55829, 55834 | Derived |
| 55828, 55832 | Unsupported write-in outcome |
| 55830, 55831, 55833, 55835 | No named candidate totals (outside the original 12) |

The actual `derive_winners --dry-run --state MA --samples 20` command was also
run against an isolated local database containing these 16 exported Council
contests: 10 derived, 2 unsupported write-in outcomes, 4 without named totals.

Before a corrective production backfill, refresh the dry-run report on the
deployed version and review its changes. Deployment and production backfill are
separate from this implementation. Run from `backend/`:

```sh
python manage.py derive_winners --dry-run --state NC --samples 10
python manage.py derive_winners --dry-run --state MA --samples 20
```

#214 still owns NC identity/seats repair and #215 still owns party population
and historical metadata backfill. This foundation does not complete those
data repairs or close the #213 tracker.
