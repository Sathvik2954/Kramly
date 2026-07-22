import logging
from abc import ABC, abstractmethod
from typing import List
import importlib

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """
    Abstract base class defining the contract for all embedding providers.
    """
    @abstractmethod
    def generate_embedding(self, text: str) -> List[float]:
        """
        Converts the input text into a high-dimensional vector.
        """
        pass


class MistralEmbeddingProvider(EmbeddingProvider):
    """
    Concrete implementation of EmbeddingProvider using Mistral's hosted
    embeddings API (POST /v1/embeddings, model "mistral-embed").

    Verified against https://docs.mistral.ai/api/endpoint/embeddings.
    Uses raw `httpx` (same pattern as `agent.llm_client`) rather than the
    `mistralai` SDK, to avoid a second HTTP-client dependency for one call.
    """
    ENDPOINT = "https://api.mistral.ai/v1/embeddings"

    def __init__(self, api_key: str = None, model_name: str = "mistral-embed"):
        if not api_key:
            from app.config import settings
            api_key = settings.mistral_api_key
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is not configured.")
        self.api_key = api_key
        self.model_name = model_name

    def generate_embedding(self, text: str) -> List[float]:
        import httpx

        try:
            response = httpx.post(
                self.ENDPOINT,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model_name, "input": text},
                timeout=20.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"Mistral embedding failed: {e}")
            raise


class SentenceTransformerProvider(EmbeddingProvider):
    """
    Concrete implementation of EmbeddingProvider using local Sentence Transformers.
    """
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Dynamically import to ensure optional dependency doesn't break app start
        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
            self.model = sentence_transformers.SentenceTransformer(model_name)
        except ImportError:
            logger.error("Failed to import 'sentence_transformers'. Please install it.")
            raise

    def generate_embedding(self, text: str) -> List[float]:
        try:
            # model.encode returns a numpy array, we convert to a standard python list
            embedding = self.model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"SentenceTransformer embedding failed: {e}")
            raise


class EmbeddingService:
    """
    Service responsible for orchestrating embedding generation.
    It relies entirely on Dependency Injection to determine which underlying
    provider actually does the math.
    """
    def __init__(self, provider: EmbeddingProvider):
        if not isinstance(provider, EmbeddingProvider):
            raise ValueError("Provider must implement EmbeddingProvider interface")
        self.provider = provider

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generates an embedding for the given text using the injected provider.
        """
        logger.debug("Generating embedding via injected provider.")
        return self.provider.generate_embedding(text)
