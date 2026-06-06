"""
JSON and HTML parsers for the PA Voter Services Candidate Database.
Uses BeautifulSoup with endswith ID matching to resiliently extract ASP.NET WebForm labels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class PaCandidateListEntry:
    candidate_id: int
    candidate_id_num: str
    name: str
    party: str
    status: str
    type_val: str
    office: str
    district: str
    election_name: str
    municipality: str
    county: str
    primary_result: bool
    general_result: bool
    cf_online_url: str


@dataclass
class PaCandidateDetailData:
    approved_date: str = ""
    candidate_type: str = ""
    ballot_lottery: str = ""
    ballot_position: str = ""
    cross_filed: str = ""
    county: str = ""
    municipality: str = ""
    cf_annual_totals_url: str = ""


def parse_candidate_list(json_str: str) -> list[PaCandidateListEntry]:
    """Parse the JSON string value of #dataJson from ElectionInfo.aspx."""
    data = json.loads(json_str)
    entries: list[PaCandidateListEntry] = []
    for row in data:
        p_res = str(row.get("PrimaryResult", "")).lower() == "true"
        g_res = str(row.get("GeneralResult", "")).lower() == "true"

        # Safe convert to int for ID
        raw_id = row.get("CandidateID")
        try:
            cand_id = int(raw_id) if raw_id is not None else 0
        except (ValueError, TypeError):
            cand_id = 0

        entries.append(
            PaCandidateListEntry(
                candidate_id=cand_id,
                candidate_id_num=row.get("CandidateIDNum", "").strip(),
                name=row.get("CandidateName", "").strip(),
                party=row.get("PartyName", "").strip(),
                status=row.get("CandidateStatusValue", "").strip(),
                type_val=row.get("CandidateTypeValue", "").strip(),
                office=row.get("OfficeName", "").strip(),
                district=row.get("DistrictName", "").strip(),
                election_name=row.get("ElectionName", "").strip(),
                municipality=row.get("Municipality", "").strip(),
                county=row.get("CountyName", "").strip(),
                primary_result=p_res,
                general_result=g_res,
                cf_online_url=row.get("CFOnlineURL", "").strip(),
            )
        )
    return entries


def parse_candidate_detail(html_str: str) -> PaCandidateDetailData:
    """Parse candidate detail page HTML."""
    soup = BeautifulSoup(html_str, "lxml")

    def get_span_text(suffix: str) -> str:
        span = soup.find(id=lambda val: val and val.endswith(suffix))
        return span.get_text(strip=True) if span else ""

    approved_date = get_span_text("lblApprovedDate")
    candidate_type = get_span_text("lblCandidateType")
    ballot_lottery = get_span_text("lblBallotLottery")
    ballot_position = get_span_text("lblBallotPosition")
    cross_filed = get_span_text("lblCrossFiled")
    county = get_span_text("lblCounty")
    municipality = get_span_text("lblMunicipality")

    # Campaign Finance Report Link
    cf_link = soup.find(id=lambda val: val and val.endswith("hlnkRptCan"))
    cf_url = cf_link.get("href", "") if cf_link else ""

    return PaCandidateDetailData(
        approved_date=approved_date,
        candidate_type=candidate_type,
        ballot_lottery=ballot_lottery,
        ballot_position=ballot_position,
        cross_filed=cross_filed,
        county=county,
        municipality=municipality,
        cf_annual_totals_url=cf_url,
    )
