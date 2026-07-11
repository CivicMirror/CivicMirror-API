from unittest.mock import MagicMock, patch

from integrations.il_sbe.client import IllinoisSbeClient


def test_fetch_election_page_replays_postback_with_captured_fields():
    client = IllinoisSbeClient()

    search_page_html = (
        '<input type="hidden" id="__VIEWSTATE" value="VSTATE123" />'
        '<input type="hidden" id="__VIEWSTATEGENERATOR" value="GEN123" />'
        '<input type="hidden" id="__EVENTVALIDATION" value="EVAL123" />'
    )
    postback_response_html = "<html>postback result</html>"

    mock_get_response = MagicMock(status_code=200, text=search_page_html)
    mock_post_response = MagicMock(status_code=200, text=postback_response_html)

    with patch.object(client._session, "get", return_value=mock_get_response) as mock_get, \
         patch.object(client._session, "post", return_value=mock_post_response) as mock_post:
        result = client.fetch_election_page("66")

    assert result == postback_response_html
    mock_get.assert_called_once()
    post_kwargs = mock_post.call_args.kwargs
    assert post_kwargs["data"]["__VIEWSTATE"] == "VSTATE123"
    assert post_kwargs["data"]["__EVENTTARGET"] == "ctl00$ContentPlaceHolder1$ddlElections"
    assert post_kwargs["data"]["ctl00$ContentPlaceHolder1$ddlElections"] == "66"


def test_fetch_category_page_passes_id_and_office_type_params():
    client = IllinoisSbeClient()
    mock_response = MagicMock(status_code=200, text="<html>category page</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_category_page("Z2J/vYpKX8w=", "LpWf6lpbWOfBN3kEuxRi3A==")

    assert result == "<html>category page</html>"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"ID": "Z2J/vYpKX8w=", "OfficeType": "LpWf6lpbWOfBN3kEuxRi3A=="}
