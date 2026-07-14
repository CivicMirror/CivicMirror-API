# Enhanced Voting — Company and Platform Research

**Research date:** July 13, 2026  
**Company website:** https://www.enhancedvoting.com/  
**Primary focus:** Enhanced Voting, LLC and its **Enhanced Results** election-results reporting platform  
**Related project:** Multi-state election-source research and reusable results-adapter development

---

## Research Scope and Evidence Standard

This document separates findings into three evidence categories:

1. **Independently confirmed** — established through government websites, live public deployments, or an independent registry.
2. **Vendor-reported** — stated by Enhanced Voting in its website, press releases, or procurement response.
3. **Technical inference** — conclusions drawn from common URLs, public APIs, application behavior, and captured network traffic.

This distinction is important. Enhanced Voting reports that its technology has been implemented in 24 states, but that statement covers its full product portfolio. It does **not** mean that Enhanced Results is used as the statewide election-night reporting system in 24 states.

---

# 1. Executive Summary

Enhanced Voting is a Jacksonville, Florida election-technology company founded in 2013 by Aaron Wilson. Its current product portfolio covers electronic ballot delivery, ballot duplication, election-results reporting, mailed-ballot tracking, and post-election ballot-image auditing.

The company's five advertised products are:

- **Enhanced Ballot**
- **Enhanced Remake**
- **Enhanced Results**
- **Ballot Scout**
- **Enhanced Audit**

For election-result research, **Enhanced Results** is the relevant product. It is a hosted election-results reporting system that accepts results from election officials, aggregates and validates the data, and publishes public-facing result pages with maps, graphs, reporting status, and contest drilldowns.

The strongest findings are:

- Enhanced Results has a recognizable and reusable public route structure.
- State and local clients may use either a government-controlled custom domain or the shared `app.enhancedvoting.com` domain.
- The same platform is confirmed on statewide result sites in Georgia, Virginia, Washington, Utah, Rhode Island, and Idaho.
- Numerous county-level installations are also publicly indexed.
- Public election identifiers are locally assigned and cannot safely be predicted.
- The platform commonly exposes a public, unauthenticated JSON API behind the browser application.
- A configuration-driven Enhanced Voting adapter is preferable to separate parsers for each state.
- The Center for Internet Security's public RABET-V registry currently lists Enhanced Ballot 3.2, Ballot Scout 3.0, and Enhanced Results 3.0 as approved products.
- RABET-V approval concerns organizational and product security practices for non-voting election technology; it is not the same as federal certification of a vote-tabulation system.

---

# 2. Company Profile

## 2.1 Basic Information

| Item | Finding | Evidence level |
|---|---|---|
| Legal/business name | Enhanced Voting, LLC | Government procurement document |
| Founded | 2013 | Company site and procurement response |
| Founder | Aaron Wilson | Company site |
| Headquarters/primary address | 13475 Atlantic Blvd., Suite 8, Jacksonville, FL 32225 | Washington procurement response |
| Primary market | State and local election administrators | Company site and public deployments |
| Business model | Hosted election software, implementation, training, support, and election-period operations | Procurement response |
| Public website | `enhancedvoting.com` | Confirmed |
| Shared results host | `app.enhancedvoting.com` | Confirmed through public deployments |

Enhanced Voting describes itself as a national provider of election-technology solutions. Its public materials emphasize security, accessibility, transparency, and products built for state and local election offices.

## 2.2 Company History

The company states that Aaron Wilson founded Enhanced Voting in 2013. The product lineage appears to begin with electronic ballot delivery for military, overseas, and disabled voters, later expanding into mailed-ballot tracking, ballot duplication, election-night reporting, and post-election auditing.

A 2025 company release described the business as operating across five product areas:

1. Mail-ballot tracking
2. Electronic ballot transmission and delivery
3. Election-night reporting
4. Post-election auditing
5. Ballot duplication

A Washington State procurement response submitted in 2025 said Enhanced Voting had implemented its technologies in 24 states. This is a vendor-reported portfolio-wide figure and should not be interpreted as 24 statewide Enhanced Results systems.

---

# 3. Leadership and Relevant Experience

The company's published leadership page identifies the following executives.

## Aaron Wilson — Founder and President

Enhanced Voting says Wilson founded the company in 2013 and leads strategy, product vision, and innovation.

His published background includes:

- Election-system security and software architecture
- Senior Director of Election Security at the Center for Internet Security
- Voting-system testing and security evaluations for the Florida Division of Elections
- Prior roles with Clear Ballot Group, Scytl, and Greenshades Software
- Work on electronic ballot-delivery deployments for military and overseas voters

## Steven Musick — Chief Technology Officer

The company describes Musick as an enterprise-architecture, cloud-computing, and distributed-systems specialist. His prior experience includes software architecture and development leadership for scalable payroll and compliance systems.

## Keir Holeman — Vice President of Election Systems

The company describes Holeman as an election professional with more than two decades of election-administration experience. His background includes local election administration and a former role with Clear Ballot Group.

## Lori Augino — Vice President of Government Relations

Augino previously served as:

- Washington State Director of Elections
- A local election official in Pierce County
- A CISA Election Security Advisor
- President of the National Association of State Election Directors

Her presence is especially relevant to Enhanced Voting's expansion into statewide election services and the Washington Enhanced Results procurement.

## Mike Garcia — Vice President of Product and Strategy

The company says Garcia's background includes:

- Cybersecurity and digital identity
- Work at the Center for Internet Security
- Participation in the creation of the EI-ISAC
- Digital-identity work at NIST
- Work on NIST Special Publication 800-63-3
- Cybersecurity strategy at the Department of Homeland Security

---

# 4. Product Portfolio

## 4.1 Enhanced Results

**Category:** Election-night and official-results reporting

Enhanced Voting describes Enhanced Results as a platform for aggregating, validating, managing, and publishing election data through public websites, maps, graphs, and result tables.

Advertised capabilities include:

- Importing data from different vote-tabulation systems
- Data-validation rules during import
- Statewide aggregation from local reporting jurisdictions
- Election and contest setup
- Real-time result updates
- Public-facing result websites
- Interactive maps and graphs
- County and precinct drilldowns
- Reporting-status displays
- Test mode before public release
- Custom branding and client text
- Election-night infrastructure and application monitoring

This is the product observed on Georgia's `results.sos.ga.gov` system.

## 4.2 Enhanced Ballot

**Category:** Electronic ballot delivery and remote ballot marking

Enhanced Ballot is marketed for:

- UOCAVA military and overseas voters
- Voters with disabilities
- Accessible absentee or vote-by-mail marking
- Accessible sample ballots
- Ballot download and printing
- Jurisdiction-specific ballot-return instructions
- In some deployments, electronic ballot return

Verified Voting describes Enhanced Ballot as a remote ballot-marking system and distinguishes it from the vendor's earlier MyBallot platform.

Electronic ballot delivery is materially different from election-results reporting. A state that uses Enhanced Ballot does not necessarily use Enhanced Results.

## 4.3 Enhanced Remake

**Category:** Ballot duplication and remake workflow

Enhanced Remake supports:

- Printing electronically delivered ballots
- Digitally remaking damaged or unreadable ballots
- Barcode scanning
- Automatic labels linking original and remade ballots
- Dual-camera observation of the duplication process
- An integrated hardware and software workstation

The product is intended for election-office operations rather than public results publication.

## 4.4 Ballot Scout

**Category:** Mailed-ballot tracking

Ballot Scout uses USPS Intelligent Mail barcode scans and election-office data to track mailed ballots.

Advertised functions include:

- Administrative tracking dashboard
- Voter-facing ballot status
- Email and SMS notifications
- Delivery-issue identification
- Maps showing the mail journey

Georgia has separately used Ballot Scout for absentee-ballot tracking, but this should not be confused with the Enhanced Results deployment.

## 4.5 Enhanced Audit

**Category:** Post-election ballot-image review and auditing

Enhanced Audit is marketed as software for:

- Reviewing ballot images
- Identifying discrepancies
- Validating election results
- Supporting post-election audit workflows

Enhanced Voting says the product was used during Georgia's 2024 general election and describes that deployment as the largest ballot-image audit conducted at that time. That scale description is a vendor claim and was not independently validated for this document.

---

# 5. Independent Security and Product Verification

## 5.1 RABET-V

The Center for Internet Security maintains a public list of products approved through the Rapid Architecture Based Election Technology Verification program.

As of July 13, 2026, the registry lists:

| Product | Provider | Version | Registry status |
|---|---|---:|---|
| Ballot Scout | Enhanced Voting | 3.0 | Approved |
| Enhanced Ballot | Enhanced Voting | 3.2 | Approved |
| Enhanced Results | Enhanced Voting | 3.0 | Approved |

CIS says participating products and organizations are assessed on their ability to build, test, monitor, and maintain election technology using evidence-based assessment, automated tools, and product testing.

## 5.2 What RABET-V Approval Does and Does Not Mean

RABET-V is designed for **non-voting election technology**, such as:

- Election-night reporting systems
- Electronic ballot-delivery systems
- Postal ballot-tracking tools
- Electronic poll books

It is not equivalent to EAC voting-system certification under the Voluntary Voting System Guidelines. Enhanced Results publishes unofficial and official results received from election administrators; it is not itself the vote-tabulation equipment that scans and counts ballots.

## 5.3 Vendor-Reported Security Practices

In its Washington procurement response, Enhanced Voting stated that:

- It was SOC 2 Type II audited and approved.
- Its solutions were audited for WCAG 2.2 AA accessibility.
- It uses Microsoft Azure for hosting and storage.
- It uses multifactor authentication for administrative access.
- It performs infrastructure, application-log, and support monitoring on election night.
- It uses automated testing, code review, quality-assurance checkpoints, and CI/CD practices.
- It supports client security review and monitoring.

These statements were made by the vendor in a selected government procurement proposal. The public proposal did not include the underlying SOC 2 report or full accessibility audit, so those reports were not independently reviewed here.

---

# 6. Enhanced Results Hosting and Delivery Model

## 6.1 Government Custom Domains

Some clients expose Enhanced Results through a government-branded domain:

| Jurisdiction | Host |
|---|---|
| Georgia | `results.sos.ga.gov` |
| Virginia | `enr.elections.virginia.gov` |
| Utah | `electionresults.utah.gov` |
| Rhode Island | `electionresults.ri.gov` |

The application remains recognizable because the path and page behavior closely match the vendor-hosted installations.

## 6.2 Shared Vendor Domain

Other installations use:

```text
https://app.enhancedvoting.com/
```

Confirmed examples include:

- Washington statewide results
- Idaho statewide or state-tenant results
- Orange County, New York
- Livingston County, New York
- Rockland County, New York
- Kent County, Michigan
- Isabella County, Michigan
- Gratiot County, Michigan

A shared domain does not imply a shared dataset. Each client is separated by a jurisdiction path segment.

## 6.3 Likely Hosting Architecture

The vendor states in its procurement material that its systems use Microsoft Azure. Public observations are consistent with a multi-tenant hosted application that supports:

- Custom hostnames
- Shared vendor hosting
- Per-jurisdiction configuration
- Per-election configuration
- A public browser application
- A JSON API
- CDN-hosted result exports
- Central software releases with client-specific branding

This architecture is a technical inference supplemented by the vendor's Azure statement.

---

# 7. Known State-Level Enhanced Results Deployments

The following statewide or state-tenant public result sites were directly observed.

| State | Public result host | Jurisdiction path | Example election identifier | Confidence |
|---|---|---|---|---|
| Georgia | `results.sos.ga.gov` | `Georgia` | `06162026GeneralPrimaryRunoff` | Confirmed by HAR and live site |
| Virginia | `enr.elections.virginia.gov` | `virginia` | `2026-April-21-Special` | Confirmed live route |
| Washington | `app.enhancedvoting.com` | `washington` | `20260428` | Confirmed live result page |
| Utah | `electionresults.utah.gov` | `Utah` | `Primary06232026` | Confirmed live result page |
| Rhode Island | `electionresults.ri.gov` | `rhodeisland` | `specaug25` | Confirmed live route |
| Idaho | `app.enhancedvoting.com` | `id` | `nov2025` | Confirmed live route |

## Procurement-Supported Deployment History

Enhanced Voting's Washington proposal additionally said:

- Virginia has used Enhanced Results since 2023.
- Utah has used Enhanced Results since 2023.
- Georgia began using Enhanced Results for the 2024 general election.
- Virginia aggregates results from 133 localities.
- Georgia aggregates results from 159 counties.
- Utah aggregates results from 29 counties and accepts files from multiple tabulation-system vendors.

Those dates and implementation descriptions come from the vendor's procurement response rather than an independent deployment registry.

---

# 8. Enhanced Results Technical Fingerprint

## 8.1 Browser Route Pattern

The common public browser route is:

```text
/results/public/{jurisdiction}/elections/{electionId}
```

Examples:

```text
https://results.sos.ga.gov/results/public/Georgia/elections/06162026GeneralPrimaryRunoff
https://enr.elections.virginia.gov/results/public/virginia/elections/2026-April-21-Special
https://app.enhancedvoting.com/results/public/washington/elections/20260428
https://electionresults.utah.gov/results/public/Utah/elections/Primary06232026
https://electionresults.ri.gov/results/public/rhodeisland/elections/specaug25
https://app.enhancedvoting.com/results/public/id/elections/nov2025
```

## 8.2 Common API Pattern

Georgia's captured application used:

```text
/results/public/api
```

Observed Georgia endpoints include:

```http
GET /jurisdictions/{jurisdiction}
GET /elections/{jurisdiction}/{electionId}
GET /elections/{jurisdiction}/{electionId}/data
GET /elections/{jurisdiction}/{electionId}/data/ballot-item/{ballotItemUuid}
GET /elections/{jurisdiction}/{electionId}/closeraces
GET /elections/{jurisdiction}/{electionId}/localities
GET /elections/{jurisdiction}/{electionId}/stats
GET /elections/{jurisdiction}/{electionId}/vr
GET /elections/{jurisdiction}/{electionId}/turnout
```

A common static/export path is:

```text
/cdn/results/{path}
```

The exact API root and available endpoints should be tested for each tenant rather than assumed solely from the public page path.

## 8.3 Common Data Concepts

The Georgia instance exposes concepts likely shared across Enhanced Results tenants:

- Jurisdiction
- Parent jurisdiction and child localities
- Elections
- Election languages
- Ballot items or contests
- Ballot options or candidates
- Count groups or vote methods
- Reporting units
- Precincts
- Polling places
- Voter registration
- Turnout
- Statistics
- Public report categories
- Media exports
- Locality-specific election data

## 8.4 Election Identifiers Are Opaque

Identifiers vary considerably:

```text
06162026GeneralPrimaryRunoff
2026-April-21-Special
20260428
Primary06232026
specaug25
nov2025
GeneralPrimary51926
2024NovGen
```

Important consequences:

- Do not generate election identifiers from dates.
- Do not assume capitalization.
- Do not assume a standard separator.
- Do not assume the jurisdiction path is a postal abbreviation or full state name.
- Discover elections through the jurisdiction endpoint whenever available.
- Preserve identifiers exactly as returned.

## 8.5 Local Configuration and Schema Drift

Enhanced Results appears highly configurable. Different deployments may vary in:

- Jurisdiction capitalization
- Election identifiers
- Contest naming
- Languages
- Vote methods
- Reporting-unit definitions
- Locality hierarchy
- Public report downloads
- Whether turnout or voter-registration sections are populated
- Whether winner flags are published
- Whether precinct data is hidden
- Whether custom explanatory text is displayed

A common adapter should therefore normalize data without assuming that every optional section is present.

---

# 9. Implementation and Support Model

Enhanced Voting's Washington proposal described a typical implementation timeline:

| Approximate point | Vendor-described activity |
|---|---|
| Week 1 | Create state instance and users; kickoff meeting |
| Week 4 | Load training data; make election-night map available; initial acceptance testing |
| Week 6 | Client supplies requested changes; vendor implements agreed changes |
| Week 8 | Train election staff |
| Election night | Vendor staff available for operational support |
| Post-election | Certification and final-reporting support |

The proposal also described:

- Test elections that are not publicly visible
- Import validation rules
- Client-specific training and documentation
- A year-round help desk
- Expanded 24/7 support during defined election periods
- Support through phone, email, ticketing, and an in-product widget
- Election-night monitoring rooms staffed by customer-success and engineering personnel
- Infrastructure, application-log, and support-inbox monitoring

These are vendor-described service practices and may vary by contract.

---

# 10. Relationship to Georgia

Georgia appears to use several Enhanced Voting products:

| Georgia function | Enhanced Voting product |
|---|---|
| Public statewide election results | Enhanced Results |
| Absentee/mail-ballot tracking | Ballot Scout |
| 2024 ballot-image audit | Enhanced Audit |
| Possible election-office ballot workflows | Other products may be contracted, but not established by the supplied HARs |

For current election-source development, only Enhanced Results is necessary.

The Georgia Enhanced Results deployment provides:

- A public jurisdiction catalog
- Historical elections
- Election metadata
- Race and candidate data
- Statewide totals
- County breakdowns
- Precinct exports
- Reporting timestamps
- Official/unofficial result status
- Downloadable reports

The presence of other Enhanced Voting products does not change the public-results ingestion strategy.

---

# 11. Implications for Multi-State Election Research

## 11.1 Treat Enhanced Voting as a Vendor Family

When a new state result site is encountered, look for:

- `/results/public/`
- `/results/public/api`
- `/cdn/results/`
- A jurisdiction segment followed by `/elections/`
- Enhanced Voting branding or footer text
- Similar contest, map, reporting, and locality pages
- JavaScript bundles referencing Enhanced Results
- UUID ballot-item routes

Once identified, research can shift from reverse-engineering a unique system to confirming the tenant configuration.

## 11.2 Recommended Discovery Workflow

1. Identify the public results host.
2. Test:

   ```http
   GET /results/public/api/jurisdictions/{candidateJurisdiction}
   ```

3. Derive the jurisdiction path from the browser URL rather than guessing it.
4. Read the returned election catalog.
5. Store the exact election ID.
6. Fetch the election `/data` endpoint.
7. Compare its schema with existing Enhanced Voting fixtures.
8. Check for a media export path.
9. Test county and precinct detail.
10. Test access from the actual cloud-worker environment.

## 11.3 Recommended Adapter Architecture

Use one shared adapter with tenant configuration.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class EnhancedVotingTenant:
    state: str
    state_name: str
    base_url: str
    jurisdiction: str


TENANTS = {
    "GA": EnhancedVotingTenant(
        state="GA",
        state_name="Georgia",
        base_url="https://results.sos.ga.gov/results/public/api",
        jurisdiction="Georgia",
    ),
    "VA": EnhancedVotingTenant(
        state="VA",
        state_name="Virginia",
        base_url="https://enr.elections.virginia.gov/results/public/api",
        jurisdiction="virginia",
    ),
    "UT": EnhancedVotingTenant(
        state="UT",
        state_name="Utah",
        base_url="https://electionresults.utah.gov/results/public/api",
        jurisdiction="Utah",
    ),
}
```

Each tenant should be enabled only after directly confirming its API root and schema.

## 11.4 Detection Heuristic

A detection routine could score a site based on:

```text
+3  URL contains /results/public/
+3  /results/public/api/jurisdictions/{slug} returns JSON
+2  Page or bundle references Enhanced Voting
+2  /cdn/results path is present
+2  Election data contains ballotItems and localityElections
+1  Ballot-item detail uses a UUID route
```

This would help categorize future states automatically while retaining manual review.

---

# 12. Risks and Caveats

## 12.1 Public API Is Not a Published Developer Contract

The JSON API is publicly accessible because the browser application uses it, but Enhanced Voting does not appear to publish a general developer API specification for third-party reuse.

Consequences:

- Endpoints may change.
- Fields may be added or removed.
- Optional fields may differ across tenants.
- A client may use configuration that hides certain data.
- Rate limits or access controls may change.
- Cloud-hosted requests may behave differently from browser requests.

Raw-source preservation and schema-drift monitoring are advisable.

## 12.2 Election-Night Reporting Is Not Vote Tabulation

Enhanced Results receives and publishes result data produced by election officials and their underlying tabulation systems. It should not be described as the system that scans or counts ballots unless a specific contract establishes that role.

## 12.3 Vendor Portfolio Does Not Equal Results Coverage

Enhanced Voting may serve a state with Enhanced Ballot, Ballot Scout, Enhanced Remake, or another product without providing that state's public election-results website.

Research databases should therefore record:

```text
vendor
product
deployment scope
jurisdiction
public host
evidence source
first observed date
last verified date
```

## 12.4 Electronic Ballot Return Is a Separate Policy and Security Issue

Some Enhanced Ballot deployments support electronic return. That function has a different security profile from:

- Downloading a blank ballot
- Marking a ballot on a device
- Printing and physically returning a ballot
- Publishing election results

It should be analyzed separately and is outside the scope of the Enhanced Results adapter.

## 12.5 Vendor Claims Should Be Labeled

Claims such as:

- “Largest ballot image audit in history”
- “Implemented in 24 states”
- Support response-time metrics
- SOC 2 and accessibility audit status
- Implementation success descriptions

should be presented as vendor-reported unless the underlying audit, contract record, or independent evidence has been reviewed.

---

# 13. Open Research Questions

1. Is there a complete public list of Enhanced Results clients?
2. Which of the 24 vendor-reported states use each specific product?
3. Are all Enhanced Results tenants hosted in the same Azure environment?
4. Do all tenants expose the jurisdiction-catalog endpoint without authentication?
5. Are the API versions identical across custom-domain and shared-domain installations?
6. Does the product expose formal cache headers, ETags, or rate-limit guidance?
7. How early before an election are election and contest records normally published?
8. How quickly do media exports update compared with the main `/data` endpoint?
9. Which fields are guaranteed by Enhanced Results 3.0 versus client-configurable?
10. Is there a public change log or release history for the Enhanced Results API?
11. Which jurisdictions use the platform only for local elections rather than statewide aggregation?
12. Are historical result migrations loaded into Enhanced Results by the vendor, the client, or both?
13. What contractual terms govern public reuse of the JSON result feeds?
14. Are RABET-V assessment summaries for Enhanced Results publicly obtainable beyond the registry entry?
15. Does every custom-domain tenant use Azure Front Door, a client CDN, or a different front-end configuration?

---

# 14. Recommended Research Record

Maintain a reusable vendor profile with tenant records.

```json
{
  "vendor": "Enhanced Voting, LLC",
  "product": "Enhanced Results",
  "product_version_observed": "3.0",
  "founded": 2013,
  "headquarters": "Jacksonville, Florida",
  "public_path_pattern": "/results/public/{jurisdiction}/elections/{electionId}",
  "api_path_pattern": "/results/public/api",
  "export_path_pattern": "/cdn/results",
  "known_state_tenants": [
    "GA",
    "VA",
    "WA",
    "UT",
    "RI",
    "ID"
  ],
  "election_id_policy": "opaque; discover from source",
  "authentication_observed": "none for public result endpoints",
  "verification": {
    "program": "RABET-V",
    "product": "Enhanced Results",
    "version": "3.0",
    "status": "Approved"
  }
}
```

---

# 15. Overall Assessment

Enhanced Voting is not merely the company behind Georgia's result-page design. It provides a broader suite of election-administration products and operates a repeatable, configurable results platform across multiple state and county clients.

For election-data engineering, the key value of identifying the vendor is architectural reuse:

- A common path structure
- A common jurisdiction/election model
- Similar JSON resources
- Shared result and export concepts
- Configurable tenant differences
- A strong basis for a reusable adapter

The Georgia research should therefore be treated as the first fully documented tenant of a larger **Enhanced Voting source family**, rather than as a one-off Georgia integration.

---

# Sources

## Official Enhanced Voting Sources

1. [Enhanced Voting home page](https://www.enhancedvoting.com/)
2. [About Enhanced Voting](https://www.enhancedvoting.com/about-us/)
3. [Enhanced Voting leadership](https://www.enhancedvoting.com/about-us/our-team/)
4. [Enhanced Results](https://www.enhancedvoting.com/solutions/enhanced-results/)
5. [Enhanced Ballot](https://www.enhancedvoting.com/solutions/enhanced-ballot/)
6. [Enhanced Remake](https://www.enhancedvoting.com/solutions/enhanced-remake/)
7. [Ballot Scout](https://www.enhancedvoting.com/solutions/ballot-scout/)
8. [Enhanced Audit](https://www.enhancedvoting.com/solutions/enhanced-audit/)
9. [Enhanced Voting security page](https://www.enhancedvoting.com/security/)
10. [Company news and releases](https://www.enhancedvoting.com/our-news/news-releases/)
11. [June 2025 RABET-V announcement](https://www.enhancedvoting.com/2025/06/17/enhanced-voting-rabetv-milestone/)

## Independent and Government Sources

12. [CIS RABET-V public product list](https://www.cisecurity.org/elections/rabetv/rabet-v-portal-public-product-list)
13. [The Turnout — Enhanced Ballot RABET-V announcement](https://turnout.rocks/our-blog/enhanced-voting-achieves-major-milestone-through-rabet-v-program-from-center-for-internet-security-and-the-turnout/)
14. [Verified Voting — Enhanced Ballot and MyBallot](https://verifiedvoting.org/election-system/enhanced-voting-myballot-and-enhancedballot/)
15. [U.S. Election Assistance Commission — Election Night Reporting Systems](https://www.eac.gov/election-technology/estep-program/election-night-report-systems)
16. [Washington Secretary of State — selected Enhanced Voting proposal](https://www.sos.wa.gov/sites/default/files/2025-08/RFQQ%2025-05%20-%20Enhanced%20Voting%20LLC%20-%20Selected%20Proposal.pdf)

## Public Enhanced Results Sites

17. [Georgia election results](https://results.sos.ga.gov/)
18. [Virginia election results](https://enr.elections.virginia.gov/)
19. [Washington Enhanced Results tenant](https://app.enhancedvoting.com/results/public/washington/elections/20260428)
20. [Utah election results](https://electionresults.utah.gov/)
21. [Rhode Island election results](https://electionresults.ri.gov/)
22. [Idaho Enhanced Results tenant](https://app.enhancedvoting.com/results/public/id/elections/nov2025)
23. [Orange County, New York results](https://app.enhancedvoting.com/results/public/orange-county-ny/elections/GE24)
24. [Kent County, Michigan results](https://app.enhancedvoting.com/results/public/kent-county-mi/elections/2024KentCountyGeneral)
25. [Livingston County, New York results](https://app.enhancedvoting.com/results/public/livingston-county-ny/elections/GE24)

---

## Related Internal Research

- `GA-Election_Research_Updated_2026-07-13.md`
- Georgia Enhanced Results HAR captures dated July 13, 2026
- Georgia June 16, 2026 media export
