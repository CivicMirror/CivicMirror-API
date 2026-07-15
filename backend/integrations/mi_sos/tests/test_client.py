from unittest.mock import MagicMock, patch

from integrations.mi_sos.client import MiSosClient


def test_fetch_votehistory_page_uses_mvic_url():
    response = MagicMock()
    response.text = "<html>ok</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_votehistory_page()

    assert text == "<html>ok</html>"
    session_cls.return_value.get.assert_called_once()
    assert "mvic.sos.state.mi.us/votehistory" in session_cls.return_value.get.call_args.args[0]


def test_fetch_candidate_listing_uses_entellitrak_report_endpoint():
    response = MagicMock()
    response.text = "<html>candidate report</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_candidate_listing("PRI", 2026)

    assert text == "<html>candidate report</html>"
    url = session_cls.return_value.get.call_args.args[0]
    params = session_cls.return_value.get.call_args.kwargs["params"]
    assert "mi-boe.entellitrak.com" in url
    assert params == {
        "page": "page.miboePublicReport",
        "electionType": "PRI",
        "electionYear": 2026,
    }


def test_fetch_result_file_uses_cf_solver_payload_fetch():
    with patch("integrations.mi_sos.client.CfSolverClient") as solver_cls:
        solver_cls.return_value.fetch_through_cf.return_value = "bulk text"
        text = MiSosClient().fetch_result_file(705)

    assert text == "bulk text"
    solve_url, payload_url = solver_cls.return_value.fetch_through_cf.call_args.args[:2]
    assert solve_url == "https://mvic.sos.state.mi.us/votehistory/"
    assert payload_url.endswith("/VoteHistory/GetElectionResultFile?electionId=705")


def test_fetch_county_vote_records_uses_plain_requests():
    response = MagicMock()
    response.text = "<html>county records</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_county_vote_records(705)

    assert text == "<html>county records</html>"
    assert "GetCountyVoteRecords" in session_cls.return_value.get.call_args.args[0]
