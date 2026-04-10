"""StubEmbeddingModel — stub embedding provider for testing."""

import hashlib
import numpy as np


class StubEmbeddingModel:
    """
    Stub embedding model that generates deterministic vectors from text.

    Used for testing semantic cache without requiring real embedding API.
    Ensures same text always produces same embedding.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    def embed(self, text: str) -> np.ndarray:
        """
        Generate deterministic embedding from text.

        Args:
            text: The text to embed

        Returns:
            Numpy array of embeddings (deterministic per text)
        """
        # Use hash to generate deterministic seed
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        np.random.seed(seed)

        # Generate random vector and normalize
        vector = np.random.randn(self._dimension).astype(np.float32)
        vector /= np.linalg.norm(vector)

        return vector
