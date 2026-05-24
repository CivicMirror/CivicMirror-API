# Anthropic TurboVote - Local Election Data Research

## 1. Executive Summary

`anthropic.turbovote.org` is a white-label deployment of TurboVote, a voter-information product built and operated by Democracy Works. Anthropic appears to host the site as an employee civic-engagement benefit and contributes no custom election data of its own.

When a user enters a street address, the site resolves that address to one or more civic jurisdictions identified by Open Civic Data (OCD) division IDs. It then queries the Democracy Works / TurboVote elections API to retrieve upcoming elections scoped to those jurisdictions. For the Sutton, MA test address (20 Welsh Rd, Sutton, MA), the system returned a local Sutton town election record tied to the OCD ID `ocd-division/country:us/state:ma/place:sutton`. That record cited an official PDF notice posted on `suttonma.org` and carried a `qa-status: complete` flag.

This strongly indicates that Democracy Works manually researches and curates local election records from official government sources rather than pulling them from a Massachusetts public elections API.

## 2. Platform Architecture: Anthropic and TurboVote

### The White-Label Site
The site `anthropic.turbovote.org` is a tenant on TurboVote's infrastructure. The site's configuration is managed through a JSON/EDN payload injected directly into the HTML source. The configuration specifies Anthropic's logo and CSS URL, sets the domain context (`anthropic.turbovote.org`), and establishes redirects (`claude.turbovote.org`).

Crucially, the configuration includes a legal disclaimer that states:
> "By using TurboVote, you agree to TurboVote's Privacy Policy and Terms of Service. You further acknowledge and agree that you are voluntarily providing your information to Democracy Works (makers of TurboVote) and not Anthropic, PBC."

There are no data overrides or supplemental API endpoints defined in this configuration payload, confirming that Anthropic uses Democracy Works' standard data pipeline.

### The Elections API
TurboVote applications retrieve election data via the Democracy Works Elections API.

According to public documentation, the API aggregates data for federal, state, county, municipal, and school board elections (typically for jurisdictions over 5,000 people). Sutton, MA has a population of 9,334, which clears this threshold.

The API lookup relies exclusively on OCD IDs. A typical query string resembles:
`?district-divisions=ocd-division/country:us/state:ma,ocd-division/country:us/state:ma/place:sutton`

## 3. How Democracy Works Sources Local Data

Democracy Works publicly documents its research methodology. The organization does not rely on a single nationwide feed for local elections (as none exists). Instead, they employ a hybrid approach:

1.  **Address to Jurisdiction Mapping:** They use tools like the Google Civic Information API to translate street addresses into sets of OCD IDs. This establishes which elections (federal, state, local) apply to the user.
2.  **Election Discovery:** Researchers track state legislation, local codes, commission meeting minutes, and municipal websites to discover upcoming elections.
3.  **Data Curation & Verification:** Democracy Works staff directly contact state and local election officials via email and phone to confirm dates and deadlines.
4.  **Ballot Data:** Specific ballot contents (candidates and measures) are sourced primarily from Ballotpedia.
5.  **Quality Assurance:** All manually curated data undergoes two rounds of QA before being marked `qa-status: complete` and exposed via the API.

## 4. Case Study: The Sutton, MA Town Election

The lookup for 20 Welsh Rd, Sutton, MA provides clear evidence of the manual curation process.

### Address Resolution
The street address is translated into its constituent jurisdictions, notably identifying the town: `ocd-division/country:us/state:ma/place:sutton`. The specific street (`20 Welsh Rd`) is not used for the local election query, as Sutton does not appear to use sub-municipal ward or precinct elections for town offices.

### The Election Record
Querying the TurboVote API for the Sutton OCD ID returns an election record. The record includes:

* **Description:** "Sutton Town Election"
* **Date:** "2026-05-26T00:00:00.000-00:00"
* **Authority Level:** Municipal
* **Registration Deadlines:** "2026-05-01T00:00:00.000-00:00" (for online, by-mail, and in-person)
* **Source:** A direct link to a PDF on the `suttonma.org` website (`https://www.suttonma.org/sites/g/files/vyhlif3901/f/uploads/20260106122617551.pdf`)

The inclusion of the PDF link is definitive proof. The timestamp in the URL indicates the PDF was uploaded to the town's website on January 6, 2026. The API record also contains a `source date` of February 9, 2026, indicating when the Democracy Works researcher found the document and logged the election details.

## 5. Massachusetts Ecosystem Context

Massachusetts currently lacks a comprehensive, programmatically accessible API for municipal election schedules and results. The state's official election statistics portal (`electionstats.state.ma.us`) is heavily protected by WAFs (Web Application Firewalls) like Imperva/Incapsula, blocking automated scraping attempts.

Consequently, aggregators like Democracy Works are forced to rely on manual collection from individual town clerk websites for municipal elections, as demonstrated by the Sutton example.

## 6. Conclusion

The election data displayed on Anthropic's TurboVote instance is entirely managed by Democracy Works. For local elections like the one in Sutton, MA, Democracy Works employs human researchers to discover and verify election dates and procedures directly from official municipal sources (such as town clerk PDFs), mapping those elections to OCD IDs. When a user enters their address, it is geocoded to an OCD ID, which is then used to retrieve the manually curated election record from the Democracy Works API.
