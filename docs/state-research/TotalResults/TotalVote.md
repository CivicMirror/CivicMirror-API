# TotalResults Election Night Reporting (ENR) Platform Research Report

**Project:** CivicMirror
**Research Date:** May 2026
**Research Scope:** TotalResults Election Night Reporting Platform Discovery, API Analysis, and Jurisdiction Enumeration

---

# Executive Summary

This research investigated the public-facing architecture of the TotalResults Election Night Reporting (ENR) platform with the goal of identifying accessible API endpoints, understanding client identification mechanisms, evaluating jurisdiction discovery methods, and determining the feasibility of building a reusable CivicMirror adapter.

The investigation confirmed that the TotalResults platform exposes a publicly accessible API used by its election reporting front-end. Through analysis of the Arkansas statewide deployment and associated network traffic, a complete workflow was identified for retrieving election metadata, contest information, and turnout data.

A key finding is that TotalResults deployments appear to be configuration-driven. Each jurisdiction deployment loads a dedicated configuration file that contains a client identifier used throughout subsequent API requests. This architecture suggests that discovering additional deployments may be significantly more effective through front-end enumeration and configuration analysis than through direct API brute-force techniques.

Testing of all fifty U.S. state names as potential client identifiers produced only one confirmed result: Arkansas. While this does not imply Arkansas is the only TotalResults customer, it indicates that client identifiers are not generally derived from state names or postal abbreviations.

The Arkansas deployment provides sufficient information to develop a reusable CivicMirror ingestion adapter capable of supporting future TotalResults jurisdictions with minimal modification.

---

# Research Objectives

The investigation sought to answer the following questions:

1. Does TotalResults expose publicly accessible election APIs?
2. How are client identifiers (`cId`) assigned and utilized?
3. Can additional jurisdictions be discovered through enumeration?
4. What API endpoints are required to collect election data?
5. Can a reusable adapter be developed for CivicMirror?

---

# Methodology

The research was conducted using the following techniques:

### API Enumeration

Testing was performed against:

```text
https://enr-results-api.totalresults.com/Election/GetElectionList
```

Various client identifier patterns were evaluated, including:

* State abbreviations
* Full state names
* County names
* Common jurisdiction naming conventions
* Test and placeholder identifiers

### Front-End Analysis

Public deployment pages were reviewed to identify:

* Client configuration files
* API endpoint usage
* Deployment structure
* Routing behavior

### HAR (HTTP Archive) Analysis

A browser network capture was collected from the Arkansas deployment to identify:

* API requests
* Configuration loading
* Application startup behavior
* Client identifier usage

---

# Platform Architecture

The TotalResults ENR platform consists of:

## Front-End Application

Public-facing deployment:

```text
https://enr.totalresults.com/<deployment>
```

Example:

```text
https://enr.totalresults.com/arkansas
```

The front-end appears to be a React-based single-page application (SPA).

## API Backend

Base API endpoint:

```text
https://enr-results-api.totalresults.com
```

The front-end communicates directly with this API to retrieve election information.

---

# Arkansas Deployment Analysis

## Confirmed Deployment

The following deployment was verified:

```text
https://enr.totalresults.com/arkansas
```

## Confirmed Client Identifier

```text
cId=arkansas
```

The following request successfully returned election metadata:

```text
https://enr-results-api.totalresults.com/Election/GetElectionList?cId=arkansas
```

The response contained election records spanning 2012–2026.

## Election Identifier Findings

The returned data revealed two identifier formats:

### Legacy Elections

Older elections use numeric identifiers:

```text
1831
1832
1833
...
1846
```

### Recent Elections

Modern elections use GUIDs:

```text
4dfe2063-3126-4eb4-ae59-1468c9d6c9cd
b412bdef-f97a-45bc-b3ec-6761d28caf9e
```

This suggests a platform migration from numeric identifiers to GUID-based identifiers occurred after approximately 2024.

---

# Configuration System

A significant discovery was the presence of a deployment-specific configuration file:

```text
https://enr.totalresults.com/arkansas/config.json
```

Example:

```json
{
  "client": "Arkansas",
  "clientStateId": "arkansas",
  "clientCountyId": "",
  "isCountyClient": false,
  "azureDeploymentPath": "/arkansas",
  "basePath": "/arkansas/"
}
```

## Architectural Significance

The configuration file indicates that:

1. Deployments are not hard-coded.
2. The application determines its client identity dynamically.
3. API requests derive their client identifier from configuration values.

Conceptually:

```text
Deployment URL
        |
        v
config.json
        |
        v
clientStateId
        |
        v
API Requests
```

This discovery substantially changes the recommended discovery methodology.

---

# API Endpoint Inventory

The HAR analysis confirmed the following endpoints are actively used by the production front-end.

## Election Metadata

```text
/Election/GetElectionList
```

Returns available elections.

```text
/Election/GetElectionInfo
```

Returns election-specific metadata.

## Contest Data

```text
/Contest/GetContestSearchList
```

Returns searchable contest listings.

```text
/Contest/GetContestResults
```

Returns detailed contest results.

## Turnout Data

```text
/Turnout/GetTurnout
```

Returns voter turnout information.

---

# Enumeration Results

## State Abbreviation Testing

Examples:

```text
AL
AK
AR
CA
TX
NY
```

Result:

```text
No valid clients discovered.
```

## Full State Name Testing

Examples:

```text
alabama
alaska
arkansas
california
texas
wyoming
```

Result:

| Client   | Elections |
| -------- | --------- |
| arkansas | 22        |

No additional states returned election data.

---

# Assessment of Discovery Methods

## Low-Value Approach

Direct API brute force:

```text
GetElectionList?cId=<guess>
```

Challenges:

* Large search space
* Unknown naming conventions
* Limited feedback from empty responses

## Recommended Approach

Enumerate deployment configurations:

```text
https://enr.totalresults.com/<candidate>/config.json
```

Advantages:

* Stronger indication of a valid deployment
* Reveals actual client identifiers
* Provides deployment metadata

---

# CivicMirror Integration Assessment

The Arkansas deployment provides a complete reference implementation for TotalResults support.

## Required Parameters

```text
cId
electionID
```

## Required Endpoints

```text
GetElectionList
GetElectionInfo
GetContestSearchList
GetContestResults
GetTurnout
```

## Reusability

Future TotalResults jurisdictions are expected to require only:

1. Discovery of deployment path
2. Extraction of client identifier
3. Reuse of existing ingestion workflow

This makes TotalResults an excellent candidate for a generic CivicMirror provider adapter.

---

# Conclusions

The investigation successfully identified and documented the core architecture of the TotalResults ENR platform.

Key findings include:

1. The TotalResults API is publicly accessible.
2. Arkansas is a confirmed statewide deployment.
3. Client identifiers are configuration-driven.
4. The platform uses deployment-specific configuration files.
5. Full-state-name enumeration discovered only Arkansas.
6. Configuration discovery is likely superior to API brute-force enumeration.
7. The Arkansas deployment exposes all functionality necessary for CivicMirror integration.
8. A reusable TotalResults adapter can be developed with minimal jurisdiction-specific customization.

---

# Recommended Next Steps

## Short-Term

1. Build the Arkansas CivicMirror adapter.
2. Implement support for all documented endpoints.
3. Normalize contest and turnout data.

## Medium-Term

1. Develop a deployment discovery utility.
2. Enumerate publicly accessible TotalResults deployments.
3. Build a registry of known jurisdictions and client identifiers.

## Long-Term

1. Generalize the adapter framework.
2. Add automatic deployment detection.
3. Expand support to county-level TotalResults customers.
4. Integrate discovered jurisdictions into CivicMirror's provider catalog.
   """
