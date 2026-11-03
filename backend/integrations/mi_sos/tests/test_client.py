from unittest.mock import MagicMock, patch

import pytest

from integrations.mi_sos.client import MiSosClient
from integrations.mi_sos.exceptions import MiSosRetryableError


def test_fetch_votehistory_page_goes_through_the_cf_solver():
    """Every mvic.sos.state.mi.us path answers a plain request with a 403 challenge."""
    with patch("integrations.mi_sos.client.CfSolverClient") as solver_cls:
        solver_cls.return_value.fetch_through_cf.return_value = "<html>ok</html>"
        text = MiSosClient().fetch_votehistory_page()

    assert text == "<html>ok</html>"
    solve_url, payload_url = solver_cls.return_value.fetch_through_cf.call_args.args[:2]
    assert solve_url == "https://mvic.sos.state.mi.us/votehistory/"
    assert payload_url == solve_url


def test_fetch_votehistory_page_maps_an_unconfigured_solver_to_a_retryable_error():
    from core.cf_solver import CfSolverUnavailableError

    with patch("integrations.mi_sos.client.CfSolverClient") as solver_cls:
        solver_cls.return_value.fetch_through_cf.side_effect = CfSolverUnavailableError("no url")
        with pytest.raises(MiSosRetryableError):
            MiSosClient().fetch_votehistory_page()


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
