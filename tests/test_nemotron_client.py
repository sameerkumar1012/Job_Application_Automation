from unittest.mock import MagicMock, patch

import pytest
import requests

from server import nemotron_client
from server.nemotron_client import (
    NemotronConfigError,
    NemotronResponseError,
    call_nemotron_json,
)


def _mock_response(content: str, status_ok: bool = True, status_code: int = 200):
    resp = MagicMock()
    resp.ok = status_ok
    resp.status_code = status_code
    resp.text = content
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_raises_config_error_when_no_api_key():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", None):
        with pytest.raises(NemotronConfigError):
            call_nemotron_json("system", "user")


def test_parses_unfenced_json():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        mock_post.return_value = _mock_response('{"answer": "hello"}')
        result = call_nemotron_json("system", "user")
        assert result == {"answer": "hello"}


def test_parses_fenced_json():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        mock_post.return_value = _mock_response('```json\n{"answer": "hello"}\n```')
        result = call_nemotron_json("system", "user")
        assert result == {"answer": "hello"}


def test_parses_prose_wrapped_json():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        content = 'Sure, here is the JSON you asked for:\n{"answer": "hello"}\nHope that helps!'
        mock_post.return_value = _mock_response(content)
        result = call_nemotron_json("system", "user")
        assert result == {"answer": "hello"}


def test_raises_response_error_on_unparseable_content():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        mock_post.return_value = _mock_response("not json at all, sorry")
        with pytest.raises(NemotronResponseError):
            call_nemotron_json("system", "user")


def test_raises_response_error_on_non_ok_status():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        mock_post.return_value = _mock_response("error body", status_ok=False, status_code=500)
        with pytest.raises(NemotronResponseError):
            call_nemotron_json("system", "user")


def test_raises_response_error_on_network_timeout():
    with patch.object(nemotron_client.config, "NVIDIA_API_KEY", "fake-key"), \
         patch.object(nemotron_client.storage, "get_settings") as mock_settings, \
         patch("server.nemotron_client.requests.post") as mock_post:
        mock_settings.return_value.model = "test-model"
        mock_post.side_effect = requests.exceptions.Timeout("Read timed out.")
        with pytest.raises(NemotronResponseError):
            call_nemotron_json("system", "user")
