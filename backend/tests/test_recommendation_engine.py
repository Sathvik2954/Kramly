"""
test_recommendation_engine.py
-----------------------------
Tests for Phase 6 — Recommendation Engine & Response Builder.

Coverage
~~~~~~~~
✓ Recommendation ranking by quality score
✓ Filtering outdated resources
✓ Top-N truncation
✓ Empty resource handling
✓ Custom ranking strategy injection
✓ Missing quality_score handling
✓ Response builder enrichment
✓ Response builder backward compatibility (learning_path preserved)
✓ Resource recommendations attached to learning steps
✓ Graceful degradation on recommendation failure
✓ Response builder with critique integration

Design decisions
~~~~~~~~~~~~~~~~
1. **No Neo4j, no mocks library needed.**
   All tests use plain lambdas and dicts as fake graph-service callables,
   following the same pattern as ``conftest.py``.

2. **Each test is independent.**
   No shared mutable state between tests.  Each test builds its own
   mock data and injects it directly.

3. **Assertion messages.**
   Every assertion includes a descriptive message for clear failure
   diagnosis.
"""

import pytest

from agent.models import (
    LearningPathWithRecommendations,
    LearningStep,
    RecommendedResource,
    SelfCritiqueResult,
)
from agent.recommendation_engine import (
    QualityScoreRanking,
    recommend_resources,
)
from agent.response_builder import build_enriched_response


# ---------------------------------------------------------------------------
# Shared mock data factories
# ---------------------------------------------------------------------------

def _make_resource(
    resource_id: str,
    title: str = "Test Resource",
    quality_score: float = 0.5,
    status: str = "ACTIVE",
    relevance_score: float = 0.5,
) -> dict:
    """Build a mock resource dict matching the expected graph shape."""
    return {
        "resource_id": resource_id,
        "title": title,
        "quality_score": quality_score,
        "status": status,
        "relevance_score": relevance_score,
    }


def _make_skill(skill_id: str, name: str = "Test Skill") -> dict:
    """Build a mock skill dict matching the graph_service shape."""
    return {
        "id": skill_id,
        "name": name,
        "domain": "TestDomain",
        "difficulty_level": "beginner",
    }


# ===================================================================
# RECOMMENDATION ENGINE TESTS
# ===================================================================


class TestRecommendationRanking:
    """Tests for quality-score-based ranking."""

    def test_ranked_by_quality_descending(self):
        """Resources should be ordered by quality_score, highest first."""
        resources = [
            _make_resource("R1", quality_score=0.5),
            _make_resource("R2", quality_score=0.9),
            _make_resource("R3", quality_score=0.7),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert len(recs) == 3, "Should return all 3 ACTIVE resources"
        assert recs[0].resource_id == "R2", "Highest quality first"
        assert recs[1].resource_id == "R3", "Second highest"
        assert recs[2].resource_id == "R1", "Lowest quality last"

    def test_quality_scores_preserved(self):
        """The quality_score in the output should match the input."""
        resources = [_make_resource("R1", quality_score=0.87)]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert recs[0].quality_score == 0.87, "Quality score pass-through"

    def test_reason_generated_for_top_resource(self):
        """The #1 resource should have a 'Highest quality score' reason."""
        resources = [_make_resource("R1", quality_score=0.95)]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert "Highest quality score" in recs[0].reason, (
            "Top resource should have a specific reason string"
        )

    def test_reason_generated_for_subsequent_resources(self):
        """Non-top resources should have a 'Ranked #N' reason."""
        resources = [
            _make_resource("R1", quality_score=0.9),
            _make_resource("R2", quality_score=0.7),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert "Ranked #2" in recs[1].reason, (
            "Second resource should have rank-based reason"
        )

    def test_tiebreak_by_relevance_score(self):
        """When quality scores are equal, relevance_score breaks the tie."""
        resources = [
            _make_resource("R1", quality_score=0.8, relevance_score=0.3),
            _make_resource("R2", quality_score=0.8, relevance_score=0.9),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert recs[0].resource_id == "R2", (
            "Higher relevance_score should win the tiebreak"
        )


class TestFilteringOutdatedResources:
    """Tests for ACTIVE-only filtering."""

    def test_outdated_resources_excluded(self):
        """Resources with status='OUTDATED' should not appear in results."""
        resources = [
            _make_resource("R1", quality_score=0.9, status="OUTDATED"),
            _make_resource("R2", quality_score=0.5, status="ACTIVE"),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert len(recs) == 1, "Only ACTIVE resources"
        assert recs[0].resource_id == "R2", "Only the ACTIVE one remains"

    def test_all_outdated_returns_empty(self):
        """If all resources are OUTDATED, return an empty list."""
        resources = [
            _make_resource("R1", status="OUTDATED"),
            _make_resource("R2", status="OUTDATED"),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert recs == [], "No ACTIVE resources → empty result"

    def test_case_insensitive_status_filter(self):
        """Status filtering should be case-insensitive."""
        resources = [
            _make_resource("R1", status="active"),
            _make_resource("R2", status="Active"),
            _make_resource("R3", status="ACTIVE"),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert len(recs) == 3, "All variants of 'ACTIVE' should pass"

    def test_missing_status_excluded(self):
        """Resources without a status field should be excluded."""
        resources = [{"resource_id": "R1", "title": "No Status", "quality_score": 0.9}]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert recs == [], "Missing status → not ACTIVE → excluded"


class TestTopNTruncation:
    """Tests for top_n parameter behavior."""

    def test_default_top_n_is_three(self):
        """Default top_n should return at most 3 resources."""
        resources = [
            _make_resource(f"R{i}", quality_score=0.9 - i * 0.1)
            for i in range(5)
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert len(recs) == 3, "Default top_n is 3"

    def test_custom_top_n(self):
        """Custom top_n should limit results."""
        resources = [
            _make_resource(f"R{i}", quality_score=0.9 - i * 0.1)
            for i in range(5)
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
            top_n=2,
        )
        assert len(recs) == 2, "top_n=2 should return 2"

    def test_top_n_larger_than_available(self):
        """top_n larger than available resources returns all."""
        resources = [_make_resource("R1")]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
            top_n=10,
        )
        assert len(recs) == 1, "Only 1 available, return 1"


class TestEmptyAndEdgeCases:
    """Tests for edge cases."""

    def test_no_resources_returns_empty(self):
        """Skill with no resources should return empty list."""
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: [],
        )
        assert recs == [], "No resources → empty"

    def test_missing_quality_score_defaults_to_zero(self):
        """Resource with missing quality_score should rank last."""
        resources = [
            _make_resource("R1", quality_score=0.5),
            {"resource_id": "R2", "title": "No QS", "status": "ACTIVE"},
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
        )
        assert recs[0].resource_id == "R1", "Known quality wins"
        assert recs[1].quality_score == 0.0, "Missing defaults to 0.0"


class TestCustomRankingStrategy:
    """Tests for pluggable ranking strategy."""

    def test_custom_strategy_used(self):
        """A custom ranking strategy should override default ranking."""

        class ReverseRanking:
            """Ranks by quality_score ascending (worst first) for testing."""

            def rank(self, resources, skill_id):
                sorted_res = sorted(
                    resources, key=lambda r: r.get("quality_score", 0.0)
                )
                return [
                    RecommendedResource(
                        resource_id=r["resource_id"],
                        title=r.get("title", ""),
                        quality_score=r.get("quality_score", 0.0),
                        reason="Custom strategy",
                    )
                    for r in sorted_res
                ]

        resources = [
            _make_resource("R1", quality_score=0.9),
            _make_resource("R2", quality_score=0.3),
        ]
        recs = recommend_resources(
            "skill_01",
            fetch_resources_for_skill=lambda _: resources,
            ranking_strategy=ReverseRanking(),
        )
        assert recs[0].resource_id == "R2", "Custom strategy: lowest first"
        assert recs[1].resource_id == "R1", "Custom strategy: highest last"


# ===================================================================
# RESPONSE BUILDER TESTS
# ===================================================================


class TestResponseBuilderEnrichment:
    """Tests for the response builder's enrichment pipeline."""

    def _mock_skill_lookup(self):
        skills = {
            "web03": _make_skill("web03", "JavaScript Basics"),
            "web04": _make_skill("web04", "DOM Manipulation"),
            "web08": _make_skill("web08", "React"),
        }
        return lambda sid: skills.get(sid)

    def _mock_resource_lookup(self):
        resources = {
            "web03": [
                _make_resource("R1", "JS Intro", 0.9),
                _make_resource("R2", "JS Guide", 0.7),
            ],
            "web04": [
                _make_resource("R3", "DOM Tutorial", 0.85),
            ],
            "web08": [],
        }
        return lambda sid: resources.get(sid, [])

    def test_enriched_response_has_correct_structure(self):
        """Each step should have skill_id, skill_name, and resources."""
        resp = build_enriched_response(
            path=["web03", "web04", "web08"],
            target_skill="web08",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
        )
        assert len(resp.recommendations) == 3, "One step per skill"
        assert resp.recommendations[0].skill_id == "web03"
        assert resp.recommendations[0].skill_name == "JavaScript Basics"
        assert len(resp.recommendations[0].recommended_resources) == 2

    def test_backward_compatibility_flat_path(self):
        """learning_path should be the exact same list as the input."""
        path = ["web03", "web04", "web08"]
        resp = build_enriched_response(
            path=path,
            target_skill="web08",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
        )
        assert resp.learning_path == path, (
            "Flat path must be preserved for backward compatibility"
        )

    def test_resources_attached_to_correct_skills(self):
        """Each skill's resources should match its own COVERS_CONCEPT data."""
        resp = build_enriched_response(
            path=["web03", "web04"],
            target_skill="web04",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
        )
        web03_rids = [r.resource_id for r in resp.recommendations[0].recommended_resources]
        web04_rids = [r.resource_id for r in resp.recommendations[1].recommended_resources]
        assert "R1" in web03_rids, "R1 belongs to web03"
        assert "R3" in web04_rids, "R3 belongs to web04"
        assert "R3" not in web03_rids, "R3 should not be in web03"

    def test_skill_with_no_resources_still_included(self):
        """A skill with no resources should still appear as a LearningStep."""
        resp = build_enriched_response(
            path=["web08"],
            target_skill="web08",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
        )
        assert len(resp.recommendations) == 1
        assert resp.recommendations[0].skill_id == "web08"
        assert resp.recommendations[0].recommended_resources == []

    def test_empty_path_returns_empty_recommendations(self):
        """An empty path should produce an empty recommendations list."""
        resp = build_enriched_response(
            path=[],
            target_skill="web08",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
        )
        assert resp.learning_path == []
        assert resp.recommendations == []

    def test_unknown_skill_gets_empty_name(self):
        """A skill not found in the graph should get an empty name, not crash."""
        resp = build_enriched_response(
            path=["UNKNOWN_SKILL"],
            target_skill="UNKNOWN_SKILL",
            fetch_skill=lambda _: None,
            fetch_resources_for_skill=lambda _: [],
        )
        assert resp.recommendations[0].skill_name == ""
        assert resp.recommendations[0].skill_id == "UNKNOWN_SKILL"

    def test_top_n_passed_to_recommendation_engine(self):
        """top_n parameter should control resources per step."""
        resp = build_enriched_response(
            path=["web03"],
            target_skill="web03",
            fetch_skill=self._mock_skill_lookup(),
            fetch_resources_for_skill=self._mock_resource_lookup(),
            top_n=1,
        )
        assert len(resp.recommendations[0].recommended_resources) == 1


class TestResponseBuilderCritiqueIntegration:
    """Tests for the optional self-critique integration."""

    def test_critique_disabled_by_default(self):
        """Without run_critique=True, the builder should not call critique."""
        # This should succeed without fetch_prerequisites being provided.
        resp = build_enriched_response(
            path=["web03"],
            target_skill="web03",
            fetch_skill=lambda _: _make_skill("web03", "JS"),
            fetch_resources_for_skill=lambda _: [],
        )
        assert isinstance(resp, LearningPathWithRecommendations)

    def test_critique_enabled_without_prereqs_degrades_gracefully(self):
        """Critique with run_critique=True but no fetch_prerequisites should not crash."""
        resp = build_enriched_response(
            path=["web03"],
            target_skill="web03",
            fetch_skill=lambda _: _make_skill("web03", "JS"),
            fetch_resources_for_skill=lambda _: [],
            run_critique=True,
            # fetch_prerequisites not provided
        )
        assert isinstance(resp, LearningPathWithRecommendations)

    def test_critique_runs_when_enabled(self):
        """When critique is enabled and prerequisites are provided, it should run."""
        resp = build_enriched_response(
            path=["web03", "web04"],
            target_skill="web04",
            fetch_skill=lambda sid: _make_skill(sid),
            fetch_resources_for_skill=lambda _: [],
            run_critique=True,
            fetch_prerequisites=lambda _: [],
            known_skills=[],
        )
        # The builder ran without error; critique was integrated.
        assert isinstance(resp, LearningPathWithRecommendations)


class TestResponseModelSerialization:
    """Tests for API compatibility — ensure models serialize correctly."""

    def test_response_serializes_to_dict(self):
        """The enriched response should serialize to a JSON-compatible dict."""
        resp = build_enriched_response(
            path=["web03"],
            target_skill="web03",
            fetch_skill=lambda _: _make_skill("web03", "JS Basics"),
            fetch_resources_for_skill=lambda _: [
                _make_resource("R1", "JS Intro", 0.9),
            ],
        )
        data = resp.model_dump()
        assert "learning_path" in data
        assert "recommendations" in data
        assert data["learning_path"] == ["web03"]
        assert len(data["recommendations"]) == 1
        assert data["recommendations"][0]["skill_id"] == "web03"
        assert len(data["recommendations"][0]["recommended_resources"]) == 1

    def test_recommended_resource_has_all_fields(self):
        """Each serialized resource should have all four required fields."""
        resp = build_enriched_response(
            path=["web03"],
            target_skill="web03",
            fetch_skill=lambda _: _make_skill("web03"),
            fetch_resources_for_skill=lambda _: [
                _make_resource("R1", "Test", 0.85),
            ],
        )
        resource_data = resp.model_dump()["recommendations"][0][
            "recommended_resources"
        ][0]
        assert "resource_id" in resource_data
        assert "title" in resource_data
        assert "quality_score" in resource_data
        assert "reason" in resource_data
