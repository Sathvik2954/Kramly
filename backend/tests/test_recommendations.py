"""
test_recommendations.py
------------------------
Tests for resource ranking + enriched response assembly.

Consolidated (renamed) from test_recommendation_engine.py — logic is
unchanged (deterministic quality_score ranking), only the import path
moved from agent.recommendation_engine / agent.response_builder to the
merged agent.recommendations module.
"""

import pytest

from agent.models import LearningPathWithRecommendations, RecommendedResource
from agent.recommendations import QualityScoreRanking, build_enriched_response, recommend_resources


def _make_resource(resource_id, title="Test Resource", quality_score=0.5, status="ACTIVE", relevance_score=0.5):
    return {
        "resource_id": resource_id, "title": title, "quality_score": quality_score,
        "status": status, "relevance_score": relevance_score,
    }


def _make_skill(skill_id, name="Test Skill"):
    return {"id": skill_id, "name": name, "domain": "TestDomain", "difficulty_level": "beginner"}


class TestRecommendationRanking:
    def test_ranked_by_quality_descending(self):
        resources = [_make_resource("R1", quality_score=0.5), _make_resource("R2", quality_score=0.9), _make_resource("R3", quality_score=0.7)]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources)
        assert [r.resource_id for r in recs] == ["R2", "R3", "R1"]

    def test_tiebreak_by_relevance_score(self):
        resources = [_make_resource("R1", quality_score=0.8, relevance_score=0.3), _make_resource("R2", quality_score=0.8, relevance_score=0.9)]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources)
        assert recs[0].resource_id == "R2"

    def test_outdated_resources_excluded(self):
        resources = [_make_resource("R1", quality_score=0.9, status="OUTDATED"), _make_resource("R2", quality_score=0.5, status="ACTIVE")]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources)
        assert len(recs) == 1 and recs[0].resource_id == "R2"

    def test_default_top_n_is_three(self):
        resources = [_make_resource(f"R{i}", quality_score=0.9 - i * 0.1) for i in range(5)]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources)
        assert len(recs) == 3

    def test_no_resources_returns_empty(self):
        assert recommend_resources("skill_01", fetch_resources_for_skill=lambda _: []) == []

    def test_missing_quality_score_defaults_to_zero(self):
        resources = [_make_resource("R1", quality_score=0.5), {"resource_id": "R2", "title": "No QS", "status": "ACTIVE"}]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources)
        assert recs[1].quality_score == 0.0

    def test_custom_ranking_strategy(self):
        class ReverseRanking:
            def rank(self, resources, skill_id):
                sorted_res = sorted(resources, key=lambda r: r.get("quality_score", 0.0))
                return [RecommendedResource(resource_id=r["resource_id"], title=r.get("title", ""), quality_score=r.get("quality_score", 0.0), reason="Custom") for r in sorted_res]

        resources = [_make_resource("R1", quality_score=0.9), _make_resource("R2", quality_score=0.3)]
        recs = recommend_resources("skill_01", fetch_resources_for_skill=lambda _: resources, ranking_strategy=ReverseRanking())
        assert recs[0].resource_id == "R2"


class TestBuildEnrichedResponse:
    def _skills(self):
        skills = {"web03": _make_skill("web03", "JavaScript Basics"), "web04": _make_skill("web04", "DOM Manipulation"), "web08": _make_skill("web08", "React")}
        return lambda sid: skills.get(sid)

    def _resources(self):
        resources = {"web03": [_make_resource("R1", "JS Intro", 0.9), _make_resource("R2", "JS Guide", 0.7)], "web04": [_make_resource("R3", "DOM Tutorial", 0.85)], "web08": []}
        return lambda sid: resources.get(sid, [])

    def test_enriched_response_structure(self):
        resp = build_enriched_response(path=["web03", "web04", "web08"], target_skill="web08", fetch_skill=self._skills(), fetch_resources_for_skill=self._resources())
        assert len(resp.recommendations) == 3
        assert resp.recommendations[0].skill_id == "web03"
        assert len(resp.recommendations[0].recommended_resources) == 2

    def test_backward_compatible_flat_path(self):
        path = ["web03", "web04", "web08"]
        resp = build_enriched_response(path=path, target_skill="web08", fetch_skill=self._skills(), fetch_resources_for_skill=self._resources())
        assert resp.learning_path == path

    def test_unknown_skill_gets_empty_name(self):
        resp = build_enriched_response(path=["UNKNOWN"], target_skill="UNKNOWN", fetch_skill=lambda _: None, fetch_resources_for_skill=lambda _: [])
        assert resp.recommendations[0].skill_name == ""

    def test_critique_disabled_by_default(self):
        resp = build_enriched_response(path=["web03"], target_skill="web03", fetch_skill=lambda _: _make_skill("web03", "JS"), fetch_resources_for_skill=lambda _: [])
        assert isinstance(resp, LearningPathWithRecommendations)
        assert resp.critique is None

    def test_critique_enabled_without_prereqs_degrades_gracefully(self):
        resp = build_enriched_response(
            path=["web03"], target_skill="web03", fetch_skill=lambda _: _make_skill("web03", "JS"),
            fetch_resources_for_skill=lambda _: [], run_critique=True,
        )
        assert isinstance(resp, LearningPathWithRecommendations)

    def test_critique_runs_when_enabled(self):
        resp = build_enriched_response(
            path=["web03", "web04"], target_skill="web04", fetch_skill=lambda sid: _make_skill(sid),
            fetch_resources_for_skill=lambda _: [], run_critique=True, fetch_prerequisites=lambda _: [], known_skills=[],
        )
        assert resp.critique is not None
        assert resp.critique.passed is True

    def test_response_serializes_to_dict(self):
        resp = build_enriched_response(path=["web03"], target_skill="web03", fetch_skill=lambda _: _make_skill("web03", "JS Basics"), fetch_resources_for_skill=lambda _: [_make_resource("R1", "JS Intro", 0.9)])
        data = resp.model_dump()
        assert data["learning_path"] == ["web03"]
        assert len(data["recommendations"][0]["recommended_resources"]) == 1
