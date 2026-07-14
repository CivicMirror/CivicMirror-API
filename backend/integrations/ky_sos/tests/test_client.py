from unittest.mock import Mock, patch

import pytest
import requests

from integrations.ky_sos.client import KentuckySosClient
from integrations.ky_sos.exceptions import KySosRetryableError


def _mock_response(status_code=200, text="<html></html>"):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = Mock()
    return resp


def test_fetch_directory_gets_root_url():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>dir</html>")) as mock_get:
        html = client.fetch_directory()
    assert html == "<html>dir</html>"
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/"


def test_fetch_office_builds_id_query_param():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>office</html>")) as mock_get:
        html = client.fetch_office(4)
    assert html == "<html>office</html>"
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/Default.aspx?id=4"


def test_fetch_withdrawn_builds_withdrawn_query_param():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>wdd</html>")) as mock_get:
        html = client.fetch_withdrawn()
    assert html == "<html>wdd</html>"
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/Default.aspx?withdrawn=1"


def test_retries_then_raises_on_persistent_5xx():
    client = KentuckySosClient(max_retries=1)
    with patch.object(client._session, "get", return_value=_mock_response(status_code=500)):
        with pytest.raises(KySosRetryableError):
            client.fetch_directory()


def test_retries_then_raises_on_connection_error():
    client = KentuckySosClient(max_retries=1)
    with patch.object(client._session, "get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(KySosRetryableError):
            client.fetch_directory()
