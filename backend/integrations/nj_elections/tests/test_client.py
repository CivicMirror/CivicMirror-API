from unittest.mock import MagicMock, patch

from integrations.nj_elections.client import NewJerseyElectionsClient


def test_fetch_enr_page_returns_response_text():
    client = NewJerseyElectionsClient()
    mock_response = MagicMock(status_code=200, text="<html>county table</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_enr_page()

    assert result == "<html>county table</html>"
    mock_get.assert_called_once()


def test_fetch_enr_page_retries_on_retryable_status():
    client = NewJerseyElectionsClient(max_retries=2)
    ok_response = MagicMock(status_code=200, text="<html>ok</html>")
    blocked_response = MagicMock(status_code=503)

    with patch.object(
        client._session, "get", side_effect=[blocked_response, ok_response]
    ) as mock_get:
        result = client.fetch_enr_page()

    assert result == "<html>ok</html>"
    assert mock_get.call_count == 2
