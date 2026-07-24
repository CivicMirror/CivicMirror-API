# Pennsylvania & New York Election Data — HAR & PDF Review

This document summarizes the findings from the review of the updated PA election research files, the accompanying HAR archive, and the New York primary certification PDF found in `.playwright-mcp/`.

---

## 1. Pennsylvania Voter Services Candidate Database Analysis

Our inspection of the HAR file (`www.pavoterservices.beta.pa.gov_Archive [26-06-06 09-55-28].har`) and the exported HTML responses has revealed the exact protocol and structure used by the PA Voter Services candidate database.

### The Hidden Data Source (`dataJson`)
The most significant finding is that candidate listing data is **not** loaded dynamically page-by-page or scraped from complex HTML tables. Instead, the page `ElectionInfo.aspx` embeds the **entire candidate dataset** for the selected election as a JSON string within a hidden input field:

```html
<input type="hidden" id="dataJson" value="[...]" />
```

A client-side Infragistics/DataTables script (`DataTable('#gvElectionInfo', { data: dataSet })`) then reads this field to render, search, and paginate the results.

### Observed JSON Candidate Schema
The JSON list contains structured details for each candidate. Below is an example entry extracted from the HAR file for a 2026 candidate:

```json
{
  "CandidateID": 161838,
  "CandidateIDNum": "2026C0020",
  "CandidateName": "CHANGE, REP IN GA STG",
  "PartyName": "Republican",
  "CandidateStatusValue": "Approved",
  "CandidateTypeValue": "Petition",
  "OfficeName": "REPRESENTATIVE IN THE GENERAL ASSEMBLY",
  "DistrictName": "55th Legislative District",
  "ElectionName": "2026 Primary Election",
  "Municipality": "102 MAIN ST",
  "CountyName": "YORK",
  "PrimaryResult": "false",
  "GeneralResult": "false",
  "CommitteeID": 0,
  "ObjectionID": "0",
  "ObjectionFileURL": "",
  "PetitionID": "Petition",
  "REPORTID": 0,
  "REPORTTEXT": null,
  "CFOnlineURL": "www.campaignfinanceonline.beta.pa.gov/Pages/CFAnnualTotals.aspx?Filer=2026C0020",
  "CandidateInfoURL": "https://www.pavoterservices.beta.pa.gov/ElectionInfo/CandidateInfo.aspx?ID="
}
```

### Automation & Scraping Workflow
Because the site is protected by Imperva/Incapsula WAF, a Playwright-based scraper is recommended to bypass challenges. The workflow is simplified by target elements:

1. **Initial Access**: Navigate to [BasicSearch.aspx](https://www.pavoterservices.beta.pa.gov/electioninfo/BasicSearch.aspx). The client-side WAF challenge completes and sets session cookies.
2. **Transition**: Navigate to [ElectionInfo.aspx](https://www.pavoterservices.beta.pa.gov/electioninfo/ElectionInfo.aspx). By default, this loads the page with the `2026 Primary Election` (value `153`) pre-selected in the dropdown.
3. **Data Extraction (Primary)**: Extract the `value` attribute from `#dataJson` and parse it as JSON to ingest all primary candidates.
4. **Election Switching (General/Specials)**:
   - Locate the select element `#ctl00_ContentPlaceHolder1_ReportElectionDropDown`.
   - Update its selection to the target election ID (e.g. `160` for the General Election).
   - This element has an `onchange` postback trigger:
     ```javascript
     onchange="javascript:setTimeout('__doPostBack(\'ctl00$ContentPlaceHolder1$ReportElectionDropDown\',\'\')', 0)"
     ```
   - Trigger the change event in Playwright, wait for the network to become idle (`networkidle`), and then read the new `#dataJson` value.

### Candidate Detail Pages (Enrichment)
To enrich candidate profiles (such as obtaining campaign finance links, petition pages, or certification status), navigate to:
`https://www.pavoterservices.beta.pa.gov/ElectionInfo/CandidateInfo.aspx?ID=<CandidateID>`

The detail page exposes:
* **Approved Date**: `ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblApprovedDate`
* **Ballot Lottery / Position**: `ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblBallotLottery` and `lblBallotPosition`
* **Campaign Finance Totals URL**: `ctl00_ContentPlaceHolder1_tabs_TabPanel5_hlnkRptCan`
* **Affidavits / Petitions downloads**: Requires postbacks on the `gvPetition` grid buttons.

---

## 2. New York State Board of Elections Certification PDF

The `.playwright-mcp/` directory contained a file named `cert_pdf_b64.json` containing a base64 encoded PDF. We successfully decoded this file.

### Document Summary
* **Title**: *Certification for the June 23, 2026 Primary Election*
* **Issuer**: New York State Board of Elections (Co-Executive Directors Kristen Zebrowski Stavisky and Raymond J. Riley III)
* **Date Certified**: May 13, 2026
* **Content**: The document lists all candidates designated by petitions to appear on the New York Primary Election ballot for public offices (Statewide, Congressional, State Senate, Assembly).

### Key Observations
* **Statewide Races**:
  * **Democratic Governor/Lt. Governor**: Kathy C. Hochul & Adrienne E. Adams (Uncontested)
  * **Republican Governor/Lt. Governor**: Bruce A. Blakeman & Todd Hood (Uncontested)
  * **Conservative Governor/Lt. Governor**: Bruce A. Blakeman & Todd Hood (Uncontested)
* **Format**: The document contains tables specifying Ballot Order, Candidate Name, and Contested status.
* **Relevance**: This document is an excellent source of truth for **Stage 1 NY Candidate Ingestion/Enrichment** and can be parsed programmatically using Python libraries like `pdfplumber` (which is already listed in `backend/requirements/base.txt`).
