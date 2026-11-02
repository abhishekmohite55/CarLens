"""Tests for fallback model logic in gemini_video and config."""
import sys
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ─── Config: ModelEntry accepts optional fallback_model ───────────────────────

def test_model_entry_has_fallback_model_field():
    from app.config import ModelEntry
    m = ModelEntry(provider="google_genai", model="gemini-3.8-flash", fallback_model="gemini-3.5-flash")
    assert m.fallback_model == "gemini-3.5-flash"


def test_model_entry_fallback_model_defaults_none():
    from app.config import ModelEntry
    m = ModelEntry(provider="google_genai", model="gemini-3.8-flash")
    assert m.fallback_model is None


# ─── Retryable error detection ────────────────────────────────────────────────

def test_503_is_retryable():
    from app.llm.gemini_video import _is_retryable
    from google.genai.errors import ServerError
    exc = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}})
    assert _is_retryable(exc) is True


def test_500_is_retryable():
    from app.llm.gemini_video import _is_retryable
    from google.genai.errors import ServerError
    exc = ServerError(500, {"error": {"code": 500, "status": "INTERNAL", "message": "internal"}})
    assert _is_retryable(exc) is True


def test_504_is_retryable():
    from app.llm.gemini_video import _is_retryable
    from google.genai.errors import ServerError
    exc = ServerError(504, {"error": {"code": 504, "status": "DEADLINE_EXCEEDED", "message": "timeout"}})
    assert _is_retryable(exc) is True


def test_429_is_retryable():
    from app.llm.gemini_video import _is_retryable
    from google.genai.errors import ClientError
    exc = ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}})
    assert _is_retryable(exc) is True


def test_400_is_not_retryable():
    from app.llm.gemini_video import _is_retryable
    from google.genai.errors import ClientError
    exc = ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "bad key"}})
    assert _is_retryable(exc) is False


def test_non_api_error_is_not_retryable():
    from app.llm.gemini_video import _is_retryable
    exc = ValueError("bad JSON")
    assert _is_retryable(exc) is False


# ─── call_gemini_video returns fallback info when fallback used ────────────────

def test_call_gemini_video_returns_fallback_info_when_used(monkeypatch):
    """When main model raises 503, fallback model is called and result carries fallback block."""
    from unittest.mock import MagicMock, patch
    from google.genai.errors import ServerError
    from app.llm import gemini_video

    # Fake upload + poll
    fake_file = MagicMock()
    fake_file.name = "files/test123"
    fake_file.state = "ACTIVE"
    fake_file.uri = "https://fake/uri"
    fake_file.mime_type = "video/mp4"

    fake_client = MagicMock()
    fake_client.files.upload.return_value = fake_file
    fake_client.files.get.return_value = fake_file

    # Main model raises 503; fallback model succeeds
    main_503 = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}})

    fake_response = MagicMock()
    fake_response.text = '{"items":[],"coverage":{}}'
    fake_response.usage_metadata.prompt_token_count = 10
    fake_response.usage_metadata.candidates_token_count = 5

    fake_client.models.generate_content.side_effect = [main_503, fake_response]

    with patch.object(gemini_video.genai, "Client", return_value=fake_client):
        msgs = []
        result = gemini_video.call_gemini_video(
            video_path=Path("/fake/video.mp4"),
            system_prompt="sys",
            user_prompt="user",
            model="gemini-3.8-flash",
            fallback_model="gemini-3.5-flash",
            temperature=0.2,
            media_resolution="low",
            timeout_sec=60,
            emit=msgs.append,
        )

    assert result["model_used"] == "gemini-3.5-flash"
    assert result["fallback"]["from"] == "gemini-3.8-flash"
    assert "503" in result["fallback"]["reason"]
    assert any("3.5-flash" in m for m in msgs)


def test_call_gemini_video_no_fallback_info_when_main_succeeds(monkeypatch):
    """When main model succeeds, result has no fallback key and model_used matches model."""
    from unittest.mock import MagicMock, patch
    from app.llm import gemini_video

    fake_file = MagicMock()
    fake_file.name = "files/abc"
    fake_file.state = "ACTIVE"
    fake_file.uri = "https://fake/uri"
    fake_file.mime_type = "video/mp4"

    fake_client = MagicMock()
    fake_client.files.upload.return_value = fake_file
    fake_client.files.get.return_value = fake_file

    fake_response = MagicMock()
    fake_response.text = '{"items":[],"coverage":{}}'
    fake_response.usage_metadata.prompt_token_count = 10
    fake_response.usage_metadata.candidates_token_count = 5
    fake_client.models.generate_content.return_value = fake_response

    with patch.object(gemini_video.genai, "Client", return_value=fake_client):
        result = gemini_video.call_gemini_video(
            video_path=Path("/fake/video.mp4"),
            system_prompt="sys",
            user_prompt="user",
            model="gemini-3.8-flash",
            fallback_model="gemini-3.5-flash",
            temperature=0.2,
            media_resolution="low",
            timeout_sec=60,
            emit=lambda m: None,
        )

    assert result.get("model_used") == "gemini-3.8-flash"
    assert "fallback" not in result


def test_call_gemini_video_both_fail_raises(monkeypatch):
    """When both main and fallback fail, raises exception naming both."""
    from unittest.mock import MagicMock, patch
    from google.genai.errors import ServerError
    from app.llm import gemini_video

    fake_file = MagicMock()
    fake_file.name = "files/abc"
    fake_file.state = "ACTIVE"
    fake_file.uri = "https://fake/uri"
    fake_file.mime_type = "video/mp4"

    fake_client = MagicMock()
    fake_client.files.upload.return_value = fake_file
    fake_client.files.get.return_value = fake_file

    err1 = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy"}})
    err2 = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy2"}})
    fake_client.models.generate_content.side_effect = [err1, err2]

    with patch.object(gemini_video.genai, "Client", return_value=fake_client):
        with pytest.raises(Exception) as exc_info:
            gemini_video.call_gemini_video(
                video_path=Path("/fake/video.mp4"),
                system_prompt="sys",
                user_prompt="user",
                model="gemini-3.8-flash",
                fallback_model="gemini-3.5-flash",
                temperature=0.2,
                media_resolution="low",
                timeout_sec=60,
                emit=lambda m: None,
            )
    msg = str(exc_info.value)
    assert "gemini-3.8-flash" in msg
    assert "gemini-3.5-flash" in msg
