"""Unit tests for the ATLAS Cloud Stack Supervisor (scripts/run_cloud_stack.py)."""

import urllib.error
from unittest.mock import MagicMock, patch

from scripts.run_cloud_stack import probe_endpoint


def test_probe_endpoint_success():
    """Verify probe_endpoint returns True when server responds with 200 OK."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert probe_endpoint("http://127.0.0.1:8000/readyz") is True


def test_probe_endpoint_failure():
    """Verify probe_endpoint returns False on network error or connection refusal."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        assert probe_endpoint("http://127.0.0.1:8000/readyz") is False
