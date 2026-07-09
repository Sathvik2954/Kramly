import pytest
from unittest.mock import MagicMock, patch

from backend.marketplace.embedding_service import (
    EmbeddingService,
    OllamaEmbeddingProvider,
    SentenceTransformerProvider,
    EmbeddingProvider
)


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


@patch("backend.marketplace.embedding_service.importlib.import_module")
def test_ollama_provider_success(mock_import):
    """Test the Ollama provider formatting and extraction."""
    # Setup mock ollama library
    mock_ollama = MagicMock()
    mock_ollama.embeddings.return_value = {"embedding": [0.5, 0.5]}
    mock_import.return_value = mock_ollama
    
    provider = OllamaEmbeddingProvider(model_name="test-model")
    result = provider.generate_embedding("Hello")
    
    assert result == [0.5, 0.5]
    mock_ollama.embeddings.assert_called_once_with(model="test-model", prompt="Hello")


@patch("backend.marketplace.embedding_service.importlib.import_module")
def test_sentence_transformer_provider_success(mock_import):
    """Test the SentenceTransformer provider numpy-to-list conversion."""
    # Setup mock numpy array structure
    mock_array = MagicMock()
    mock_array.tolist.return_value = [0.9, 0.1]
    
    # Setup mock ST model
    mock_model = MagicMock()
    mock_model.encode.return_value = mock_array
    
    # Setup mock ST library
    mock_st_lib = MagicMock()
    mock_st_lib.SentenceTransformer.return_value = mock_model
    mock_import.return_value = mock_st_lib
    
    provider = SentenceTransformerProvider(model_name="test-mini")
    result = provider.generate_embedding("World")
    
    assert result == [0.9, 0.1]
    mock_model.encode.assert_called_once_with("World")
    mock_st_lib.SentenceTransformer.assert_called_once_with("test-mini")


@patch("backend.marketplace.embedding_service.importlib.import_module")
def test_provider_import_failure(mock_import):
    """Test graceful failure if the underlying library isn't installed."""
    mock_import.side_effect = ImportError("No module named ollama")
    
    with pytest.raises(ImportError):
        OllamaEmbeddingProvider()
