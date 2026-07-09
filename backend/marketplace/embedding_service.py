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


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Concrete implementation of EmbeddingProvider using the Ollama API.
    """
    def __init__(self, model_name: str = "mxbai-embed-large"):
        self.model_name = model_name
        
        # Dynamically import to prevent hard-crashing if library is missing in some environments
        try:
            self.ollama = importlib.import_module("ollama")
        except ImportError:
            logger.error("Failed to import 'ollama'. Please install it.")
            raise

    def generate_embedding(self, text: str) -> List[float]:
        try:
            response = self.ollama.embeddings(model=self.model_name, prompt=text)
            return response.get("embedding", [])
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
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
