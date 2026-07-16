from unittest.mock import MagicMock, patch

import pytest

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.exceptions import MnSosRetryableError


def test_file_url_builds_host_datepath_filename():
    assert MnSosClient.file_url("20241105", "ussenate.txt") == (
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt"
    )


def test_file_exists_true_on_200():
    client = MnSosClient()
    with patch.object(client._session, "head", return_value=MagicMock(status_code=200)) as head:
        assert client.file_exists("20241105", "USPres.txt") is True
    assert head.call_args.args[0] == (
        "https://electionresultsfiles.sos.mn.gov/20241105/USPres.txt"
    )


def test_file_exists_false_on_404():
    client = MnSosClient()
    with patch.object(client._session, "head", return_value=MagicMock(status_code=404)):
        assert client.file_exists("20251104", "USPres.txt") is False


def test_file_exists_retries_then_raises_on_persistent_5xx():
    client = MnSosClient(max_retries=1)
    with patch.object(client._session, "head", return_value=MagicMock(status_code=503)):
        with pytest.raises(MnSosRetryableError):
            client.file_exists("20241105", "USPres.txt")


def test_fetch_file_index_passes_ers_election_id_param():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="<html>index</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file_index(170)

    assert result == "<html>index</html>"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"ersElectionId": 170}
    assert "Select/MediaFiles/Index" in mock_get.call_args.args[0]


def test_fetch_file_index_raises_retryable_on_radware_captcha_200():
    client = MnSosClient()
    captcha_html = (
        "<html><head><title>Radware Captcha Page</title></head>"
        "<body>Please verify you are human.</body></html>"
    )
    mock_response = MagicMock(status_code=200, text=captcha_html)

    with patch.object(client._session, "get", return_value=mock_response):
        with pytest.raises(MnSosRetryableError):
            client.fetch_file_index(170)


def test_fetch_file_index_allows_real_index_containing_perfdrive_telemetry():
    # The legitimate index page contains "validate.perfdrive.com" in its
    # stormcaster telemetry config — that string must NOT be read as a CAPTCHA.
    client = MnSosClient()
    real_html = (
        '<html><head><title>Index - Election Results</title></head>'
        '<body><script>ssConf("cu", "validate.perfdrive.com, ssc");</script>'
        '<a class="downloadlink" href="https://x/USPres.txt">U.S. President Statewide</a>'
        "</body></html>"
    )
    mock_response = MagicMock(status_code=200, text=real_html)

    with patch.object(client._session, "get", return_value=mock_response):
        result = client.fetch_file_index(170)

    assert result == real_html


def test_fetch_file_gets_the_given_url_directly():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="MN;;;0102;...")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")

    assert result == "MN;;;0102;..."
    mock_get.assert_called_once_with(
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt", timeout=30
    )


def test_fetch_candidate_table_uses_date_path():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="01020202;Amy Klobuchar;...")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_candidate_table("20241105")

    assert result == "01020202;Amy Klobuchar;..."
    mock_get.assert_called_once_with(
        "https://electionresultsfiles.sos.mn.gov/20241105/cand.txt", timeout=30
    )


def test_fetch_file_retries_then_raises_on_persistent_5xx():
    client = MnSosClient(max_retries=1)
    mock_response = MagicMock(status_code=503, text="")

    with patch.object(client._session, "get", return_value=mock_response):
        with pytest.raises(MnSosRetryableError):
            client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")
