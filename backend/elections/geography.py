"""
Infer a race's geography_scope from its office title.

Used for races bootstrapped from results feeds, which carry only a contest name. Those races used
to be hard-coded to "statewide", so county boards, city councils, and school boards were all
labeled statewide (16k+ NC races alone).

Canonical values produced here:
    federal     U.S. President, Senate, House
    statewide   offices elected by the whole state (Governor, AG, Supreme Court, ...)
    district    a sub-state district: state legislature, judicial/prosecutorial district, ward, ...
    countywide  county offices and county-wide boards
    local       municipal, township, school-board and special-district offices
    ""          unknown: the title doesn't say. Never guessed as "statewide".
"""
from __future__ import annotations

import re

FEDERAL = "federal"
STATEWIDE = "statewide"
DISTRICT = "district"
COUNTYWIDE = "countywide"
LOCAL = "local"
UNKNOWN = ""

_FEDERAL_RE = re.compile(
    r"\b(U\.?\s?S\.?|UNITED STATES)\s+(SENATE|SENATOR|HOUSE|REPRESENTATIVE|CONGRESS)"
    r"|\bCONGRESS(IONAL)?\b|^PRESIDENT\b|\bPRESIDENT\s+(AND|&)\s+VICE",
    re.I,
)
# Checked before "county": school boards, municipal and special-district offices are local even
# when the title names a county (e.g. "BURKE COUNTY BOARD OF EDUCATION").
_LOCAL_RE = re.compile(
    r"\b(CITY|TOWN|VILLAGE|BOROUGH|TOWNSHIP|MUNICIPAL(ITY)?|MAYOR|ALDERM[AE]N|ALDERPERSON|"
    r"SCHOOLS?|BOARD OF EDUCATION|SCHOOL DIRECTOR|SOIL AND WATER|ABC STORES?|SANITARY|"
    r"FIRE (PROTECTION )?DISTRICT|WATER DISTRICT|PARK DISTRICT|LIBRARY DISTRICT|HOSPITAL DISTRICT)\b",
    re.I,
)
_COUNCIL_RE = re.compile(r"\bCOUNCIL(MAN|WOMAN|MEMBER|OR)?\b", re.I)
_STATE_COUNCIL_RE = re.compile(r"\b(GOVERNOR'?S|EXECUTIVE)\s+COUNCIL\b", re.I)
_COUNTY_RE = re.compile(
    r"\bCOUNTY\b|\bCOUNTYWIDE\b|\bPARISH\b|\bSHERIFF\b|\bASSESSOR\b|\bJUSTICE OF THE PEACE\b|"
    r"\bREGISTER OF DEEDS\b|\bCLERK OF (THE )?(SUPERIOR|CIRCUIT) COURT\b|"
    r"\bCORONER\b|\bREGISTER OF PROBATE\b|\bPROBATE JUDGE\b",
    re.I,
)
_DISTRICT_RE = re.compile(
    r"\bDISTRICT\b|\bDIST\.|\bWARD\b|\bPRECINCT\b|\bSTATE\s+(HOUSE|SENATE|SENATOR|REPRESENTATIVE|ASSEMBLY)\b|"
    r"\bHOUSE OF (REPRESENTATIVES|DELEGATES)\b|\bGENERAL ASSEMBLY\b",
    re.I,
)
_STATEWIDE_RE = re.compile(
    r"\bLIEUTENANT GOVERNOR\b|^(STATE\s+|[A-Z]{2}\s+)?GOVERNOR\b|\bATTORNEY GENERAL\b|"
    r"\bSECRETARY OF (STATE|THE COMMONWEALTH)\b|\bSTATE TREASURER\b|\bTREASURER OF STATE\b|"
    r"\bSTATE AUDITOR\b|\bAUDITOR OF (STATE|PUBLIC ACCOUNTS)\b|\bCOMPTROLLER\b|"
    r"\bCOMMISSIONER OF (AGRICULTURE|INSURANCE|LABOR|PUBLIC LANDS|PUBLIC LANDS AND)\b|"
    r"\b(STATE )?SUPERINTENDENT OF PUBLIC INSTRUCTION\b|\bSUPREME COURT\b|\bCOURT OF APPEALS\b|"
    r"\bCOURT OF CRIMINAL APPEALS\b|\bCONSTITUTIONAL AMENDMENT\b|\bSTATEWIDE\b|"
    r"^(TREASURER|AUDITOR|CONTROLLER)$",
    re.I,
)


def infer_geography_scope(office_title: str | None) -> str:
    """Return a canonical geography_scope for an office title, or "" when it can't be told."""
    title = " ".join((office_title or "").split())
    if not title:
        return UNKNOWN
    if _FEDERAL_RE.search(title):
        return FEDERAL
    if _STATE_COUNCIL_RE.search(title):
        return DISTRICT  # e.g. MA Governor's Council: elected by district
    if _LOCAL_RE.search(title):
        return LOCAL
    if _COUNTY_RE.search(title):
        return COUNTYWIDE
    if _DISTRICT_RE.search(title):
        return DISTRICT
    if _STATEWIDE_RE.search(title):
        return STATEWIDE
    if _COUNCIL_RE.search(title):
        return LOCAL
    return UNKNOWN
