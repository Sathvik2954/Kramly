"""
test_providers.py
Tests for the two external-provider integration points in this codebase:
the Groq/Mistral chat client (agent/llm_client.py) and the embedding
providers (marketplace/embedding_service.py). Consolidated from
test_llm_client.py + test_embeddings.py since both are "talk to a hosted
API, no local model" concerns.

All tests mock httpx.post - no real network calls, no real API keys needed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_client import LLMClient, LLMUnavailableError
from backend.marketplace.embedding_service import (
    EmbeddingService,
    MistralEmbeddingProvider,
    SentenceTransformerProvider,
    EmbeddingProvider
)


def _fake_response(content: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


# ===================================================================
# agent/llm_client.py - Groq primary / Mistral fallback chat client
# ===================================================================

class TestProviderSelection:
    def test_no_keys_configured_raises_immediately(self):
        client = LLMClient()
        assert client.has_any_provider is False
        with pytest.raises(LLMUnavailableError):
            client.complete("sys", "user")

    @patch("agent.llm_client.httpx.post")
    def test_groq_used_when_configured(self, mock_post):
        mock_post.return_value = _fake_response("groq answer")
        client = LLMClient(groq_api_key="gk", mistral_api_key="mk")

        result = client.complete("sys", "user")

        assert result == "groq answer"
        assert mock_post.call_count == 1
        called_url = mock_post.call_args[0][0]
        assert "groq.com" in called_url

    @patch("agent.llm_client.httpx.post")
    def test_falls_back_to_mistral_when_groq_fails(self, mock_post):
        def side_effect(url, **kwargs):
            if "groq.com" in url:
                raise RuntimeError("groq is down")
            return _fake_response("mistral answer")

        mock_post.side_effect = side_effect
        client = LLMClient(groq_api_key="gk", mistral_api_key="mk")

        result = client.complete("sys", "user")

        assert result == "mistral answer"
        assert mock_post.call_count == 2

    @patch("agent.llm_client.httpx.post")
    def test_both_providers_failing_raises(self, mock_post):
        mock_post.side_effect = RuntimeError("network down")
        client = LLMClient(groq_api_key="gk", mistral_api_key="mk")

        with pytest.raises(LLMUnavailableError):
            client.complete("sys", "user")

    @patch("agent.llm_client.httpx.post")
    def test_only_mistral_configured_skips_groq(self, mock_post):
        mock_post.return_value = _fake_response("mistral only")
        client = LLMClient(mistral_api_key="mk")

        result = client.complete("sys", "user")

        assert result == "mistral only"
        assert mock_post.call_count == 1
        assert "mistral.ai" in mock_post.call_args[0][0]


class TestJsonMode:
    @patch("agent.llm_client.httpx.post")
    def test_valid_json_parsed(self, mock_post):
        mock_post.return_value = _fake_response(json.dumps({"should_replan": True, "reasoning": "ok"}))
        client = LLMClient(groq_api_key="gk")

        result = client.complete_json("sys", "user")

        assert result == {"should_replan": True, "reasoning": "ok"}

    @patch("agent.llm_client.httpx.post")
    def test_invalid_json_retries_then_succeeds(self, mock_post):
        mock_post.side_effect = [
            _fake_response("not json at all"),
            _fake_response(json.dumps({"ok": True})),
        ]
        client = LLMClient(groq_api_key="gk")

        result = client.complete_json("sys", "user")

        assert result == {"ok": True}
        assert mock_post.call_count == 2

    @patch("agent.llm_client.httpx.post")
    def test_invalid_json_after_retry_raises(self, mock_post):
        mock_post.return_value = _fake_response("still not json")
        client = LLMClient(groq_api_key="gk")

        with pytest.raises(LLMUnavailableError):
            client.complete_json("sys", "user")


# ===================================================================
# marketplace/embedding_service.py - Mistral / SentenceTransformer
# embedding providers
# ===================================================================

def test_embedding_service_requires_valid_provider():
    """Test that the orchestrator rejects invalid providers at instantiation."""
    class FakeProvider:
        pass

    with pytest.raises(ValueError, match="Provider must implement EmbeddingProvider interface"):
        EmbeddingService(provider=FakeProvider())


def test_embedding_service_delegates_to_provider():
    """Test that the service successfully passes the call to a valid provider."""
    mock_provider = MagicMock(spec=EmbeddingProvider)
    mock_provider.generate_embedding.return_value = [0.1, 0.2, 0.3]

    service = EmbeddingService(provider=mock_provider)
    result = service.generate_embedding("Test text")

    assert result == [0.1, 0.2, 0.3]
    mock_provider.generate_embedding.assert_called_once_with("Test text")


@patch("httpx.post")
def test_mistral_embedding_provider_success(mock_post):
    """Test the Mistral embedding provider request/response handling."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": [{"embedding": [0.5, 0.5], "index": 0, "object": "embedding"}]}
    mock_post.return_value = mock_response

    provider = MistralEmbeddingProvider(api_key="fake-key", model_name="mistral-embed")
    result = provider.generate_embedding("Hello")

    assert result == [0.5, 0.5]
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "api.mistral.ai" in call_kwargs[0][0]


def test_mistral_embedding_provider_requires_api_key():
    """Without an api_key argument and no MISTRAL_API_KEY configured, should raise."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.mistral_api_key = None
        with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
            MistralEmbeddingProvider()


@patch("backend.marketplace.embedding_service.importlib.import_module")
def test_sentence_transformer_provider_success(mock_import):
    """Test the SentenceTransformer provider numpy-to-list conversion."""
    mock_array = MagicMock()
    mock_array.tolist.return_value = [0.9, 0.1]

    mock_model = MagicMock()
    mock_model.encode.return_value = mock_array

    mock_st_lib = MagicMock()
    mock_st_lib.SentenceTransformer.return_value = mock_model
    mock_import.return_value = mock_st_lib

    provider = SentenceTransformerProvider(model_name="test-mini")
    result = provider.generate_embedding("World")

    assert result == [0.9, 0.1]
    mock_model.encode.assert_called_once_with("World")
    mock_st_lib.SentenceTransformer.assert_called_once_with("test-mini")


@patch("backend.marketplace.embedding_service.importlib.import_module")
def test_sentence_transformer_import_failure(mock_import):
    """Test graceful failure if the underlying library isn't installed."""
    mock_import.side_effect = ImportError("No module named sentence_transformers")

    with pytest.raises(ImportError):
        SentenceTransformerProvider()
