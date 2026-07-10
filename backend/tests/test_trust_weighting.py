"""
test_trust_weighting.py
-----------------------
Tests for Phase 6 — Trust Weighting & Planner Integration.

Coverage
~~~~~~~~
✓ Inverse confidence weighting formula
✓ Linear discount weighting formula
✓ Custom formula injection
✓ Edge-case handling (zero confidence, full confidence, epsilon)
✓ Single-edge calculation via calculate_edge_weight
✓ Batch processing via apply_trust_weights
✓ TrustWeightedEdge model correctness
✓ Planner standard mode (backward compatibility)
✓ Planner trust-aware mode (weighted topological sort)
✓ Trust-aware mode preserves prerequisite ordering
✓ Trust-aware mode changes ordering based on confidence
✓ Missing edge weights default correctly

Design decisions
~~~~~~~~~~~~~~~~
- Planner integration tests reuse the fake graph from ``conftest.py``.
- Formula tests use exact numeric assertions with tolerances.
- Each weighting formula is tested independently.
"""

import pytest

from agent.models import TrustWeightedEdge
from agent.trust_weighting import (
    apply_trust_weights,
    calculate_edge_weight,
    inverse_confidence_weighting,
    linear_discount_weighting,
)
from optimizer.planner import generate_learning_path


# ===================================================================
# INVERSE CONFIDENCE WEIGHTING TESTS
# ===================================================================


class TestInverseConfidenceWeighting:
    """Tests for the default inverse_confidence_weighting formula."""

    def test_high_confidence_low_cost(self):
        """High confidence should produce a lower cost."""
        w = inverse_confidence_weighting(1.0, 0.9)
        assert w < 1.5, f"High confidence should yield low cost, got {w}"

    def test_low_confidence_high_cost(self):
        """Low confidence should produce a higher cost."""
        w = inverse_confidence_weighting(1.0, 0.1)
        assert w > 5.0, f"Low confidence should yield high cost, got {w}"

    def test_cost_monotonically_decreases_with_confidence(self):
        """As confidence increases, cost should decrease."""
        costs = [
            inverse_confidence_weighting(1.0, c)
            for c in [0.1, 0.3, 0.5, 0.7, 0.9]
        ]
        for i in range(len(costs) - 1):
            assert costs[i] > costs[i + 1], (
                f"Cost should decrease: {costs[i]} > {costs[i+1]}"
            )

    def test_zero_confidence_uses_epsilon(self):
        """Zero confidence should not cause division by zero."""
        w = inverse_confidence_weighting(1.0, 0.0)
        assert w > 0, "Should be finite (epsilon prevents div-by-zero)"
        assert w == pytest.approx(1.0 / 0.01, rel=1e-3), (
            "Should equal base / epsilon"
        )

    def test_full_confidence_formula(self):
        """Full confidence (1.0) should yield base / (1.0 + epsilon)."""
        w = inverse_confidence_weighting(1.0, 1.0)
        expected = 1.0 / (1.0 + 0.01)
        assert w == pytest.approx(expected, rel=1e-3)

    def test_base_weight_scales_result(self):
        """Doubling the base weight should double the cost."""
        w1 = inverse_confidence_weighting(1.0, 0.5)
        w2 = inverse_confidence_weighting(2.0, 0.5)
        assert w2 == pytest.approx(w1 * 2, rel=1e-3)

    def test_min_weight_floor(self):
        """Result should never go below min_weight."""
        w = inverse_confidence_weighting(0.0, 1.0, min_weight=0.05)
        assert w >= 0.05, "Should be clamped to min_weight"

    def test_custom_epsilon(self):
        """Custom epsilon should be respected."""
        w = inverse_confidence_weighting(1.0, 0.0, epsilon=0.1)
        assert w == pytest.approx(1.0 / 0.1, rel=1e-3)


# ===================================================================
# LINEAR DISCOUNT WEIGHTING TESTS
# ===================================================================


class TestLinearDiscountWeighting:
    """Tests for the linear_discount_weighting formula."""

    def test_full_confidence_halves_cost(self):
        """With factor=0.5 and confidence=1.0, cost should be halved."""
        w = linear_discount_weighting(1.0, 1.0, discount_factor=0.5)
        assert w == pytest.approx(0.5, rel=1e-3)

    def test_zero_confidence_preserves_base(self):
        """With confidence=0.0, cost should equal base_weight."""
        w = linear_discount_weighting(1.0, 0.0, discount_factor=0.5)
        assert w == pytest.approx(1.0, rel=1e-3)

    def test_partial_confidence(self):
        """With confidence=0.5 and factor=0.5, cost = base * 0.75."""
        w = linear_discount_weighting(1.0, 0.5, discount_factor=0.5)
        expected = 1.0 * (1.0 - 0.5 * 0.5)
        assert w == pytest.approx(expected, rel=1e-3)

    def test_full_discount_factor(self):
        """With factor=1.0 and confidence=1.0, cost should be min_weight."""
        w = linear_discount_weighting(1.0, 1.0, discount_factor=1.0)
        assert w == pytest.approx(0.01, rel=1e-3), (
            "Full discount should hit min_weight floor"
        )

    def test_min_weight_floor(self):
        """Result should never go below min_weight."""
        w = linear_discount_weighting(
            0.5, 1.0, discount_factor=1.0, min_weight=0.1
        )
        assert w >= 0.1


# ===================================================================
# CALCULATE_EDGE_WEIGHT TESTS
# ===================================================================


class TestCalculateEdgeWeight:
    """Tests for the single-edge public API."""

    def test_default_formula_is_inverse(self):
        """Default formula should be inverse_confidence_weighting."""
        w_direct = inverse_confidence_weighting(1.0, 0.8)
        w_api = calculate_edge_weight(1.0, 0.8)
        assert w_api == pytest.approx(w_direct, rel=1e-6)

    def test_custom_formula_injection(self):
        """A custom formula should be used when provided."""
        custom = lambda base, conf: base * (2.0 - conf)
        w = calculate_edge_weight(1.0, 0.8, formula=custom)
        assert w == pytest.approx(1.2, rel=1e-3)

    def test_returns_float(self):
        """Result should always be a float."""
        w = calculate_edge_weight(1.0, 0.5)
        assert isinstance(w, float)


# ===================================================================
# APPLY_TRUST_WEIGHTS (BATCH) TESTS
# ===================================================================


class TestApplyTrustWeights:
    """Tests for batch edge processing."""

    def test_produces_trust_weighted_edges(self):
        """Output should be a list of TrustWeightedEdge models."""
        edges = [
            {
                "source_skill": "web03",
                "target_skill": "web04",
                "base_weight": 1.0,
                "crowd_confidence": 0.9,
            },
        ]
        result = apply_trust_weights(edges)
        assert len(result) == 1
        assert isinstance(result[0], TrustWeightedEdge)

    def test_fields_correctly_mapped(self):
        """All input fields should be correctly mapped to the model."""
        edges = [
            {
                "source_skill": "A",
                "target_skill": "B",
                "base_weight": 2.0,
                "crowd_confidence": 0.7,
            },
        ]
        result = apply_trust_weights(edges)
        edge = result[0]
        assert edge.source_skill == "A"
        assert edge.target_skill == "B"
        assert edge.base_weight == 2.0
        assert edge.crowd_confidence == 0.7
        assert edge.final_weight > 0

    def test_high_confidence_lower_final_weight(self):
        """Higher confidence should produce lower final_weight."""
        edges = [
            {
                "source_skill": "A",
                "target_skill": "B",
                "base_weight": 1.0,
                "crowd_confidence": 0.9,
            },
            {
                "source_skill": "C",
                "target_skill": "D",
                "base_weight": 1.0,
                "crowd_confidence": 0.2,
            },
        ]
        result = apply_trust_weights(edges)
        assert result[0].final_weight < result[1].final_weight, (
            "Higher confidence → lower cost"
        )

    def test_default_base_weight_when_missing(self):
        """Missing base_weight should default to 1.0."""
        edges = [
            {
                "source_skill": "A",
                "target_skill": "B",
                "crowd_confidence": 0.5,
            },
        ]
        result = apply_trust_weights(edges)
        assert result[0].base_weight == 1.0

    def test_default_confidence_when_missing(self):
        """Missing crowd_confidence should default to 1.0."""
        edges = [
            {
                "source_skill": "A",
                "target_skill": "B",
                "base_weight": 1.0,
            },
        ]
        result = apply_trust_weights(edges)
        assert result[0].crowd_confidence == 1.0

    def test_empty_edges_returns_empty(self):
        """Empty input should return empty list."""
        assert apply_trust_weights([]) == []

    def test_custom_formula_applied_to_batch(self):
        """A custom formula should be used for all edges in the batch."""
        constant_formula = lambda base, conf: 42.0
        edges = [
            {"source_skill": "A", "target_skill": "B"},
            {"source_skill": "C", "target_skill": "D"},
        ]
        result = apply_trust_weights(edges, formula=constant_formula)
        for edge in result:
            assert edge.final_weight == 42.0


# ===================================================================
# PLANNER INTEGRATION TESTS
# ===================================================================


class TestPlannerStandardMode:
    """Verify that the planner's standard mode is fully backward-compatible."""

    def test_standard_mode_unchanged(self, fake_graph):
        """Without edge_weights, planner behavior should be identical."""
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            **fake_graph,
        )
        assert "web08" in path, "Target should be in path"
        assert "web01" not in path, "Known skills should not appear"
        assert "web02" not in path, "Known skills should not appear"

    def test_prerequisite_ordering_preserved(self, fake_graph):
        """Prerequisites should always come before dependents."""
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            **fake_graph,
        )
        # web03 → web04, web03 → web05
        assert path.index("web03") < path.index("web04")
        assert path.index("web03") < path.index("web05")

    def test_empty_edge_weights_not_passed(self, fake_graph):
        """Calling without edge_weights should work (no kwarg)."""
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            fetch_skill=fake_graph["fetch_skill"],
            fetch_all_prereqs_recursive=fake_graph["fetch_all_prereqs_recursive"],
            fetch_prereq_edges=fake_graph["fetch_prereq_edges"],
        )
        assert len(path) > 0


class TestPlannerTrustAwareMode:
    """Verify that trust-aware mode correctly uses edge weights."""

    def test_trust_aware_reorders_based_on_confidence(self, fake_graph):
        """High-confidence edges should be preferred in ordering."""
        # Make the web07 path much cheaper than web03/web04/web05
        weights = {
            ("web02", "web03"): 10.0,   # low confidence → expensive
            ("web02", "web07"): 0.1,    # high confidence → cheap
            ("web03", "web04"): 10.0,
            ("web03", "web05"): 10.0,
            ("web04", "web08"): 10.0,
            ("web05", "web08"): 10.0,
            ("web07", "web08"): 0.1,
        }
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            edge_weights=weights,
            **fake_graph,
        )
        assert path.index("web07") < path.index("web03"), (
            "web07 should come first due to lower cost"
        )

    def test_trust_aware_same_skills_as_standard(self, fake_graph):
        """Trust-aware mode should include the same set of skills."""
        path_standard = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            **fake_graph,
        )
        weights = {
            ("web02", "web03"): 5.0,
            ("web02", "web07"): 0.5,
            ("web03", "web04"): 5.0,
            ("web03", "web05"): 5.0,
            ("web04", "web08"): 5.0,
            ("web05", "web08"): 5.0,
            ("web07", "web08"): 0.5,
        }
        path_trust = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            edge_weights=weights,
            **fake_graph,
        )
        assert set(path_standard) == set(path_trust), (
            "Same skills, potentially different order"
        )

    def test_trust_aware_preserves_hard_prerequisites(self, fake_graph):
        """Even with weights, hard prerequisite constraints must hold."""
        weights = {
            ("web02", "web03"): 0.1,
            ("web02", "web07"): 10.0,
            ("web03", "web04"): 0.1,
            ("web03", "web05"): 0.1,
            ("web04", "web08"): 0.1,
            ("web05", "web08"): 0.1,
            ("web07", "web08"): 10.0,
        }
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            edge_weights=weights,
            **fake_graph,
        )
        # Hard prerequisite constraints must hold regardless of weights.
        assert path.index("web03") < path.index("web04")
        assert path.index("web03") < path.index("web05")

    def test_trust_aware_with_empty_weights(self, fake_graph):
        """An empty weights dict should work (all edges default to 1.0)."""
        path = generate_learning_path(
            known_skills=["web01", "web02"],
            target_skill="web08",
            edge_weights={},
            **fake_graph,
        )
        assert "web08" in path

    def test_trust_aware_cycle_detection(self, cyclic_graph):
        """Trust-aware mode should still detect cycles."""
        from optimizer.exceptions import CycleDetected

        with pytest.raises(CycleDetected):
            generate_learning_path(
                known_skills=[],
                target_skill="target",
                edge_weights={("A", "B"): 1.0, ("B", "C"): 1.0, ("C", "A"): 1.0},
                **cyclic_graph,
            )
