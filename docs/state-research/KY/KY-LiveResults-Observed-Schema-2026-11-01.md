# KY `/liveresults/Data` — observed live schema (2026-11-01)

Captured by reading the six datasets in a browser on 2026-11-01, during the
2026 General Election window (votes all zero; election day is Nov 3).

**The shipped `results/adapters/ky.py` cannot read this feed.** It was written
from the "Data Website Guide" PDF in this directory, which is **v4
(Oct 2024)** and describes an *attribute*-based schema with `snake_case` names.
The live feed is *element*-based WCF DataContract XML with PascalCase names and
different field names entirely. Nothing matches.

## Transport

- Base: `https://vrsws.sos.ky.gov/liveresults/Data/<Dataset>` (no `.xml`)
- Namespace: `http://schemas.datacontract.org/2004/07/SBE.ENR.Web.Public.Wrappers`
- All datasets reachable: `Elections`, `Contests`, `Candidates`,
  `CurrentResults`, `CurrentResultsExcludeLocal`, `GeopoliticalUnits`,
  `PoliticalParties`

## Elections — one current election, and NO ElectionId

```xml
<Election>
  <ElectionDate>2026-11-03T00:00:00</ElectionDate>
  <ElectionName>2026 General Election</ElectionName>
  <ElectionType>General</ElectionType>
</Election>
```

Consequences:
- There is **no `ElectionId` anywhere in the feed** -- not on `Election`, not on
  `Contest` (verified: zero `ElectionId` elements in the Contests document).
  The feed is implicitly scoped to the current election.
- The date is ISO-8601 with a time component, not `MM/DD/YYYY`.
- The `?id=2026` in the dashboard URL is a site selector, unrelated.

## Contests — `<ArrayOfContest>`, 3,626 records

```xml
<Contest>
  <ContestId>1039</ContestId>
  <ContestName>CHARTER AMENDMENT 1</ContestName>
  <ContestScopeUnitId>36</ContestScopeUnitId>
  <DisplayOrder>498036001</DisplayOrder>
  <IsPartisan>false</IsPartisan>
  <IsUncontested>false</IsUncontested>
  <IsUnexpiredTerm>false</IsUnexpiredTerm>
  <PoliticalPartyId>0</PoliticalPartyId>
  <SelectableOption>1</SelectableOption>
</Contest>
```

No `ElectionId`. No `GovernmentScopeUnitId` / `FilingScopeUnitId` /
`OfficeScopeUnitId` (the v4 guide lists all three).

Caution: contest names are **not unique and carry no county qualifier** --
`CIRCUIT CLERK` appears many times with distinct ContestIds and
`ContestScopeUnitId=2` (the State unit), which is not a usable jurisdiction
hint for county-level offices. Race matching cannot rely on name alone.

## Candidates — `<ArrayOfCandidate>`

```xml
<Candidate><BallotName>Andy BARR</BallotName><CandidateId>2</CandidateId>
<ContestId>1</ContestId><IsIncumbent>false</IsIncumbent>
<IsWithdrawn>false</IsWithdrawn><IsWriteIn>false</IsWriteIn>
<PoliticalPartyId>2</PoliticalPartyId></Candidate>
```

Write-ins are real records: `<BallotName>Write-In</BallotName>`,
`<IsWriteIn>true</IsWriteIn>`. No `ElectionId`.

## CurrentResultsExcludeLocal — `<SummaryReport>`

Two wrapper children, each holding items of the *same* tag name, so
`getElementsByTagName` hits the wrapper first -- iterate the wrapper's children:

```xml
<SummaryReport>
  <CandidateData>
    <CandidateData>
      <CandidateId>2</CandidateId><ContestId>1</ContestId>
      <ElectionDayVotes>0</ElectionDayVotes>
      <ReportingUnitId>2</ReportingUnitId>
      <TotalVotes>0</TotalVotes>
    </CandidateData>
    ...
  </CandidateData>
  <ReportData>
    <ReportData>
      <BallotsCast>0</BallotsCast><PrecinctsParticipating>3189</PrecinctsParticipating>
      <PrecinctsReporting>0</PrecinctsReporting><RegisteredVoters>3393480</RegisteredVoters>
      <ReportingStatus>NotReporting</ReportingStatus><ReportingUnitId>2</ReportingUnitId>
    </ReportData>
    ...
  </ReportData>
</SummaryReport>
```

**The join key is `ReportingUnitId`, not `gpu_id`/`Gup_id`.** Field names are
`TotalVotes`, `ElectionDayVotes`, `ReportingStatus`, `BallotsCast`,
`PrecinctsParticipating`, `PrecinctsReporting`, `RegisteredVoters` -- all
PascalCase elements, none matching the v4 guide's `snake_case` attributes. The
`Gup_id` typo the adapter defends against does not exist in this schema.

## GeopoliticalUnits — `<ArrayOfGeopoliticalUnit>`, 3,896 units

```xml
<GeopoliticalUnit><ParentId>1</ParentId><UnitId>2</UnitId>
<UnitName>Kentucky</UnitName><UnitType>State</UnitType></GeopoliticalUnit>
```

**`UnitType` is a name, not the numeric code the v4 guide tabulates.**
Observed values: `Country` (1), `State` (1), `County` (120), `City` (413),
`School` (171), `Precinct` (3190). So `_UNIT_TYPE_STATE = "11"` never matches;
it must be `"State"`. Kentucky is `UnitId=2`, which is the one thing the guide
got right.

## PoliticalParties

```xml
<PoliticalParty><Abbreviation>DEM</Abbreviation><PartyId>1</PartyId>
<PartyName>Democratic</PartyName></PoliticalParty>
```

## The jurisdiction fan-out, measured

`CurrentResultsExcludeLocal` holds **84,638 CandidateData rows** across **254
contests**. Distinct (contest, unit) pairs by unit type:

| Unit type | pairs |
|---|---|
| State | 254 |
| County | 931 |
| Precinct | 31,944 |

So the fan-out is real and large: ~33k sub-jurisdiction rows against 254
contest totals. This confirms the `jurisdiction_fragment` bug empirically --
without a `""` row, `/races/{id}/results` would serve the whole breakdown and
`results.winners` would derive nothing.

Good news for the fix's design: **all 254 contests have both a State row and a
row at their own `ContestScopeUnitId`** (zero contests had neither), so the
scope-unit-then-state fallback chain resolves a total for every contest in this
feed. The "district contest with no district row" case does not arise here --
though note `ExcludeLocal` excludes local contests, so `CurrentResults` (the
full feed) may behave differently.

## What this means for `ky.py`

Every field read is wrong, so the adapter yields **zero rows** even with
network access -- and fails earlier than that: `select_ky_election_id` looks for
an `ElectionId` that does not exist, returns `""`, and the adapter bails with
"No matching Kentucky ElectionId found in Elections XML". The policy block has
been masking a parser that could never have worked.

Rewrite needed:
1. Read child elements, not attributes (`_attr` -> a `_child_text` helper).
2. Drop `ElectionId` from the data model; scope by the single current election
   and verify `ElectionDate`/`ElectionType` match the target Election instead.
3. `_safe_date` must accept `YYYY-MM-DDTHH:MM:SS`.
4. Rename every field per the tables above; `ReportingUnitId` replaces `gpu_id`.
5. Iterate the `CandidateData`/`ReportData` wrapper children, not
   `getElementsByTagName`.
6. `_UNIT_TYPE_STATE = "State"`, `_UNIT_TYPE_COUNTY = "County"`.
7. Keep the contest-total / breakdown-fragment logic -- it is validated above.
