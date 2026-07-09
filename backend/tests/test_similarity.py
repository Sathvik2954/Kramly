from unittest.mock import MagicMock

from backend.marketplace.similarity_service import (
    calculate_similarity,
    find_similar_resources,
    detect_duplicates
)


def test_calculate_similarity():
    """Test that cosine similarity math is correct."""
    # Orthogonal vectors (no similarity)
    assert calculate_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    
    # Identical vectors (perfect similarity)
    assert calculate_similarity([1.0, 2.0], [1.0, 2.0]) == 1.0
    
    # Opposite vectors
    assert calculate_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_find_similar_resources():
    """Test that finding similar resources correctly triggers the edge creation."""
    target_embedding = [1.0, 1.0]
    
    mock_embeddings = {
        "RES_A": [1.0, 1.0],  # Score 1.0 (Exact duplicate logically)
        "RES_B": [1.0, 0.9],  # Very similar
        "RES_C": [-1.0, -1.0] # Not similar
    }
    
    mock_fetch_embeddings = MagicMock(return_value=mock_embeddings)
    mock_create_edge = MagicMock()
    
    results = find_similar_resources(
        target_resource_id="TARGET",
        target_embedding=target_embedding,
        similarity_threshold=0.5,
        fetch_embeddings_func=mock_fetch_embeddings,
        create_edge_func=mock_create_edge,
        is_duplicate_threshold=0.98
    )
    
    # Should only return RES_A and RES_B (both > 0.5)
    assert len(results) == 2
    
    # Since it's sorted descending
    assert results[0].resource_b == "RES_A"
    assert results[0].is_duplicate is True
    assert results[1].resource_b == "RES_B"
    
    # Edge should have been created twice (for A and B)
    assert mock_create_edge.call_count == 2


def test_detect_duplicates_exact_and_near():
    """Test the exact hash match and near-duplicate embedding logic."""
    target_embedding = [1.0, 0.0, 0.0]
    target_hash = "abc123hash"
    
    # RES_EXACT has the same hash, different embedding (simulated anomaly, hash should win)
    # RES_NEAR has different hash, identical embedding
    mock_hashes = {
        "RES_EXACT": "abc123hash",
        "RES_NEAR": "xyz987hash",
        "RES_NORMAL": "differenthash"
    }
    
    mock_embeddings = {
        "RES_EXACT": [0.0, 1.0, 0.0], 
        "RES_NEAR": [1.0, 0.0, 0.0],
        "RES_NORMAL": [0.0, 0.0, 1.0]
    }
    
    duplicates = detect_duplicates(
        target_resource_id="TARGET",
        target_hash=target_hash,
        target_embedding=target_embedding,
        is_duplicate_threshold=0.95,
        fetch_hashes_func=MagicMock(return_value=mock_hashes),
        fetch_embeddings_func=MagicMock(return_value=mock_embeddings)
    )
    
    # Should find RES_EXACT (hash) and RES_NEAR (embedding)
    assert len(duplicates) == 2
    
    # Validate the exact duplicate
    exact = next(d for d in duplicates if d.resource_b == "RES_EXACT")
    assert exact.similarity_score == 1.0
    assert exact.is_duplicate is True
    
    # Validate the near duplicate
    near = next(d for d in duplicates if d.resource_b == "RES_NEAR")
    assert near.similarity_score == 1.0  # Cosine math makes it 1.0
    assert near.is_duplicate is True
