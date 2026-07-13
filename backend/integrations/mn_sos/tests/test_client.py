from unittest.mock import MagicMock, patch

import pytest

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.exceptions import MnSosRetryableError


def test_fetch_file_index_passes_ers_election_id_param():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="<html>index</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file_index(170)

    assert result == "<html>index</html>"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"ersElectionId": 170}
    assert "Select/MediaFiles/Index" in mock_get.call_args.args[0]


def test_fetch_file_gets_the_given_url_directly():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="MN;;;0102;...")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")

    assert result == "MN;;;0102;..."
    mock_get.assert_called_once_with(
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt", timeout=30
    )


def test_fetch_file_retries_then_raises_on_persistent_5xx():
    client = MnSosClient(max_retries=1)
    mock_response = MagicMock(status_code=503, text="")

    with patch.object(client._session, "get", return_value=mock_response):
        with pytest.raises(MnSosRetryableError):
            client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")
