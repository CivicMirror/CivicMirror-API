from __future__ import annotations

import textwrap


def test_parse_candidate_report_csv_extracts_and_normalizes_rows():
    from integrations.hi_olvr.parsers import parse_candidate_report_csv

    csv_bytes = textwrap.dedent("""\
        "Contests","Party","BallotName","LegalName","MailingAddress","CityStateZip","Phone","Email","Website","IssueDate","FilingDate","Status"
        "U.S. REPRESENTATIVE, DIST I","DEMOCRATIC","BELATTI, Della Au","DELLA AU BELATTI ","P.O. BOX 900","HONOLULU, HI 96808","8083930594","della@example.com","www.example.com","02/17/2026","06/01/2026","In Primary"
        "GOVERNOR","DEMOCRATIC","ISSUED ONLY","ISSUED ONLY","","","","","","02/17/2026","","Issued"
    """).encode()

    rows = parse_candidate_report_csv(csv_bytes)

    assert len(rows) == 2
    assert rows[0].contest == "U.S. REPRESENTATIVE, DIST I"
    assert rows[0].ballot_name == "BELATTI, Della Au"
    assert rows[0].legal_name == "DELLA AU BELATTI"
    assert rows[0].issue_date.isoformat() == "2026-02-17"
    assert rows[1].status == "Issued"
