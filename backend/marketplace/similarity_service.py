import logging
import math
from typing import List, Callable, Optional, Dict

from .models import SimilarityResult

logger = logging.getLogger(__name__)

# Type aliases for dependency injection
FetchResourceEmbeddings = Callable[[], Dict[str, List[float]]]
FetchResourceHashes = Callable[[], Dict[str, str]]
CreateSimilarEdge = Callable[[str, str, float], None]


def calculate_similarity(embedding_a: List[float], embedding_b: List[float]) -> float:
    """
    Computes the cosine similarity between two vectors.
    Returns a float between -1.0 and 1.0 (typically 0.0 to 1.0 for embeddings).
    """
    if len(embedding_a) != len(embedding_b):
        raise ValueError("Embeddings must be of the same dimensionality.")
    
    dot_product = sum(a * b for a, b in zip(embedding_a, embedding_b))
    norm_a = math.sqrt(sum(a * a for a in embedding_a))
    norm_b = math.sqrt(sum(b * b for b in embedding_b))
    
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
        
    return dot_product / (norm_a * norm_b)


def create_similarity_relationship(
    resource_a_id: str,
    resource_b_id: str,
    score: float,
    create_edge_func: CreateSimilarEdge
) -> None:
    """
    Persists the similarity relationship to the graph database using the injected function.
    """
    logger.debug(f"Creating SIMILAR_TO edge between {resource_a_id} and {resource_b_id} (score: {score:.3f})")
    create_edge_func(resource_a_id, resource_b_id, score)


def find_similar_resources(
    target_resource_id: str,
    target_embedding: List[float],
    similarity_threshold: float,
    fetch_embeddings_func: FetchResourceEmbeddings,
    create_edge_func: CreateSimilarEdge,
    is_duplicate_threshold: float = 0.95
) -> List[SimilarityResult]:
    """
    Finds resources similar to the target embedding, creates graph relationships
    if they exceed the similarity threshold, and returns the results.
    
    Args:
        target_resource_id: ID of the resource being compared.
        target_embedding: The embedding vector of the target resource.
        similarity_threshold: Minimum score required to establish a SIMILAR_TO relationship.
        fetch_embeddings_func: Injected function returning all existing resource embeddings.
        create_edge_func: Injected function to create the graph relationship.
        is_duplicate_threshold: Score above which resources are flagged as duplicates.
        
    Returns:
        A list of SimilarityResult objects for resources that met the threshold.
    """
    results = []
    
    # 1. Fetch all existing embeddings from storage (via Person A's graph_service abstraction)
    existing_resources = fetch_embeddings_func()
    
    for resource_id, embedding in existing_resources.items():
        # Prevent self-comparison
        if resource_id == target_resource_id:
            continue
            
        # 2. Compute cosine similarity
        try:
            score = calculate_similarity(target_embedding, embedding)
        except ValueError as e:
            logger.warning(f"Failed to compare {target_resource_id} with {resource_id}: {e}")
            continue
            
        # 3. Compare against configurable threshold
        if score >= similarity_threshold:
            # 4. Create SIMILAR_TO relationship
            create_similarity_relationship(
                resource_a_id=target_resource_id,
                resource_b_id=resource_id,
                score=score,
                create_edge_func=create_edge_func
            )
            
            is_duplicate = score >= is_duplicate_threshold
            
            # 5. Build and store the result
            result = SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=score,
                is_duplicate=is_duplicate
            )
            results.append(result)
            
    # Sort results by highest score first
    results.sort(key=lambda x: x.similarity_score, reverse=True)
    return results


def detect_duplicates(
    target_resource_id: str,
    target_hash: str,
    target_embedding: List[float],
    is_duplicate_threshold: float,
    fetch_hashes_func: FetchResourceHashes,
    fetch_embeddings_func: FetchResourceEmbeddings
) -> List[SimilarityResult]:
    """
    Detects both exact duplicates (via hash comparison) and near-duplicates 
    (via embedding cosine similarity).
    
    Args:
        target_resource_id: ID of the resource being checked.
        target_hash: Cryptographic hash of the resource's content (provided by Person A).
        target_embedding: Embedding vector of the resource.
        is_duplicate_threshold: Configurable threshold for near-duplicates (e.g. 0.98).
        fetch_hashes_func: Injected function returning all existing resource hashes.
        fetch_embeddings_func: Injected function returning all existing resource embeddings.
        
    Returns:
        List of SimilarityResult indicating which resources are duplicates.
    """
    duplicates = []
    
    # 1. Exact Duplicate Detection (Hash Comparison)
    existing_hashes = fetch_hashes_func()
    for resource_id, resource_hash in existing_hashes.items():
        if resource_id == target_resource_id:
            continue
            
        if resource_hash == target_hash:
            logger.info(f"Exact duplicate found! {target_resource_id} matches hash of {resource_id}")
            duplicates.append(SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=1.0,
                is_duplicate=True
            ))
            
    # 2. Near Duplicate Detection (Embedding Comparison)
    existing_embeddings = fetch_embeddings_func()
    for resource_id, embedding in existing_embeddings.items():
        if resource_id == target_resource_id:
            continue
            
        # Skip if we already flagged as exact duplicate
        if any(d.resource_b == resource_id for d in duplicates):
            continue
            
        try:
            score = calculate_similarity(target_embedding, embedding)
        except ValueError:
            continue
            
        if score >= is_duplicate_threshold:
            logger.info(f"Near duplicate found! {target_resource_id} is similar to {resource_id} (Score: {score:.3f})")
            duplicates.append(SimilarityResult(
                resource_a=target_resource_id,
                resource_b=resource_id,
                similarity_score=score,
                is_duplicate=True
            ))
            
    return duplicates
