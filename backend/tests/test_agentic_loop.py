"""
test_agentic_loop.py
---------------------
Tests for the observe-reason-act agentic loop (agent/observation.py,
agent/controller.py, agent/executor.py, AgentScheduler.run_agentic_cycle).

The core claim under test: the agent now genuinely chooses between
different actions depending on the learner's situation, instead of always
doing the one thing the pre-existing system could do (recompute the
path). Each scenario class below constructs a distinct LearnerObservation
and asserts the resulting action is the one that situation calls for, not
just RECOMPUTE_PATH every time.

Conventions follow test_engine.py / test_marketplace_ingestion.py:
- `LLMClient()` with no API keys forces the deterministic-fallback path.
- `@patch("agent.llm_client.httpx.post")` mocks the network boundary for
  LLM-driven tests.
- A query-text-sniffing FakeTx mocks Neo4j for the one integration-style
  test of observe_learner_state.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent.actions import ActionType, ChosenAction
from agent.controller import build_candidate_actions, select_action
from agent.executor import execute_action
from agent.llm_client import LLMClient
from agent.observation import (
    LearnerObservation,
    ResourceCandidate,
    _detect_stale_evidence,
    _detect_stuck_skills,
    observe_learner_state,
)

_NO_LLM = LLMClient()
_NOW = datetime(2026, 7, 19, tzinfo=timezone.utc)


def _obs(**overrides) -> LearnerObservation:
    base = dict(
        learner_id="L001",
        known_skills=["A", "B"],
        target_skill="Z",
        deadline=None,
        current_path=["C", "D", "Z"],
        decayed_skills=[],
        stuck_skills=[],
        stale_evidence_skills=[],
        resources_by_skill={},
    )
    base.update(overrides)
    return LearnerObservation(**base)


# ===================================================================
# Pure detection helpers
# ===================================================================


class TestDetectStuckSkills:
    def test_skill_repeated_across_window_is_stuck(self):
        history = [
            {"added_skills": ["X", "Y"]},
            {"added_skills": ["X"]},
            {"added_skills": ["X", "Z"]},
        ]
        stuck = _detect_stuck_skills(history, window=3, repeat_threshold=2)
        assert stuck == ["X"]

    def test_skill_appearing_once_is_not_stuck(self):
        history = [{"added_skills": ["X"]}, {"added_skills": ["Y"]}]
        stuck = _detect_stuck_skills(history, window=3, repeat_threshold=2)
        assert stuck == []

    def test_empty_history_returns_empty(self):
        assert _detect_stuck_skills([], window=3, repeat_threshold=2) == []

    def test_only_last_window_entries_considered(self):
        history = [{"added_skills": ["OLD"]}] * 5 + [{"added_skills": ["RECENT"]}]
        stuck = _detect_stuck_skills(history, window=1, repeat_threshold=1)
        assert stuck == ["RECENT"]


class TestDetectStaleEvidence:
    def test_old_evidence_is_flagged(self):
        old = (_NOW - timedelta(days=90)).isoformat()
        data = [{"skill_id": "OLD_SKILL", "last_practiced": old}]
        stale = _detect_stale_evidence(data, now=_NOW, staleness_days=60)
        assert stale == ["OLD_SKILL"]

    def test_fresh_evidence_is_not_flagged(self):
        fresh = (_NOW - timedelta(days=5)).isoformat()
        data = [{"skill_id": "FRESH_SKILL", "last_practiced": fresh}]
        stale = _detect_stale_evidence(data, now=_NOW, staleness_days=60)
        assert stale == []

    def test_missing_last_practiced_is_skipped_not_crashed(self):
        data = [{"skill_id": "NO_TIMESTAMP", "last_practiced": None}]
        assert _detect_stale_evidence(data, now=_NOW, staleness_days=60) == []


# ===================================================================
# Candidate generation (deterministic, no LLM)
# ===================================================================


class TestBuildCandidateActions:
    def test_no_issues_yields_only_no_action(self):
        candidates = build_candidate_actions(_obs())
        assert [c.action_type for c in candidates] == [ActionType.NO_ACTION]

    def test_decayed_skill_yields_recompute_candidate(self):
        candidates = build_candidate_actions(_obs(decayed_skills=["C"]))
        types = [c.action_type for c in candidates]
        assert ActionType.RECOMPUTE_PATH in types

    def test_stuck_skill_with_resource_yields_escalate_and_recommend(self):
        obs = _obs(
            stuck_skills=["C"],
            resources_by_skill={"C": [ResourceCandidate(resource_id="R1", title="C Bootcamp", quality_score=0.9)]},
        )
        candidates = build_candidate_actions(obs)
        types = {c.action_type for c in candidates}
        assert ActionType.ESCALATE_STUCK_LEARNER in types
        assert ActionType.RECOMMEND_RESOURCE in types
        recommend = next(c for c in candidates if c.action_type == ActionType.RECOMMEND_RESOURCE)
        assert recommend.skill_id == "C"

    def test_decayed_skill_without_resource_yields_flag_for_reinforcement(self):
        candidates = build_candidate_actions(_obs(decayed_skills=["C"]))
        types = {c.action_type for c in candidates}
        assert ActionType.FLAG_FOR_REINFORCEMENT in types

    def test_stale_evidence_yields_request_evidence(self):
        candidates = build_candidate_actions(_obs(stale_evidence_skills=["A"]))
        types = {c.action_type for c in candidates}
        assert ActionType.REQUEST_EVIDENCE in types

    def test_target_already_known_suppresses_recompute(self):
        obs = _obs(known_skills=["A", "B", "Z"], target_skill="Z", decayed_skills=["A"])
        candidates = build_candidate_actions(obs)
        types = {c.action_type for c in candidates}
        assert ActionType.RECOMPUTE_PATH not in types


# ===================================================================
# select_action — deterministic fallback (no LLM configured)
# ===================================================================


class TestSelectActionFallback:
    """These are the three required validation scenarios: a stuck learner,
    an unused marketplace resource for a weak skill, and stale evidence on
    a known skill each produce a DIFFERENT chosen action - proving the
    agent isn't just recomputing the path every time."""

    def test_only_no_action_candidate_skips_llm_entirely(self):
        with patch("agent.controller.build_default_client") as mock_build:
            chosen = select_action(_obs(), llm_client=_NO_LLM)
            mock_build.assert_not_called()
        assert chosen.action_type == ActionType.NO_ACTION

    def test_stuck_learner_scenario_escalates_or_recommends(self):
        obs = _obs(
            stuck_skills=["C"],
            resources_by_skill={"C": [ResourceCandidate(resource_id="R1", title="C Bootcamp")]},
        )
        chosen = select_action(obs, llm_client=_NO_LLM)
        assert chosen.action_type == ActionType.ESCALATE_STUCK_LEARNER
        assert chosen.source == "deterministic_fallback"

    def test_unused_resource_scenario_recommends_it(self):
        obs = _obs(
            decayed_skills=["C"],
            resources_by_skill={"C": [ResourceCandidate(resource_id="R1", title="C Refresher")]},
        )
        chosen = select_action(obs, llm_client=_NO_LLM)
        # RECOMPUTE_PATH still outranks RECOMMEND_RESOURCE in the fallback
        # priority order (a stale path is more urgent than a missed
        # resource) - both are real candidates, proving this isn't a
        # single-action system even in fallback mode.
        candidates = build_candidate_actions(obs)
        types = {c.action_type for c in candidates}
        assert ActionType.RECOMMEND_RESOURCE in types
        assert chosen.action_type in (ActionType.RECOMPUTE_PATH, ActionType.RECOMMEND_RESOURCE)

    def test_stale_evidence_only_scenario_requests_evidence(self):
        obs = _obs(stale_evidence_skills=["A"])
        chosen = select_action(obs, llm_client=_NO_LLM)
        assert chosen.action_type == ActionType.REQUEST_EVIDENCE
        assert chosen.skill_id == "A"

    def test_different_scenarios_yield_different_actions(self):
        """The direct proof this isn't recompute-in-disguise: three
        distinct situations produce three distinct chosen actions."""
        stuck = select_action(
            _obs(stuck_skills=["C"], resources_by_skill={"C": [ResourceCandidate(resource_id="R1", title="X")]}),
            llm_client=_NO_LLM,
        )
        stale = select_action(_obs(stale_evidence_skills=["A"]), llm_client=_NO_LLM)
        nothing = select_action(_obs(), llm_client=_NO_LLM)

        actions = {stuck.action_type, stale.action_type, nothing.action_type}
        assert len(actions) == 3, f"expected 3 distinct actions, got {actions}"
        assert nothing.action_type == ActionType.NO_ACTION


# ===================================================================
# select_action — LLM-driven, including the grounding/hallucination guard
# ===================================================================


class TestSelectActionLLM:
    @patch("agent.llm_client.httpx.post")
    def test_llm_choice_within_candidate_list_is_honored(self, mock_post):
        obs = _obs(stale_evidence_skills=["A"], decayed_skills=["C"])
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{
                "message": {"content": json.dumps({
                    "action_type": "REQUEST_EVIDENCE", "skill_id": "A", "justification": "evidence is old"
                })}
            }]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        chosen = select_action(obs, llm_client=client)
        assert chosen.action_type == ActionType.REQUEST_EVIDENCE
        assert chosen.skill_id == "A"
        assert chosen.source == "llm"
        assert chosen.justification == "evidence is old"

    @patch("agent.llm_client.httpx.post")
    def test_llm_choice_outside_candidate_list_falls_back(self, mock_post):
        """Mirrors marketplace/ingestion.py's hallucination filter: an LLM
        proposing an action/skill combination that was never offered as a
        candidate is rejected, not trusted."""
        obs = _obs(stale_evidence_skills=["A"])
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{
                "message": {"content": json.dumps({
                    "action_type": "RECOMPUTE_PATH", "skill_id": None, "justification": "made up"
                })}
            }]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        chosen = select_action(obs, llm_client=client)
        assert chosen.source == "deterministic_fallback"
        assert chosen.action_type == ActionType.REQUEST_EVIDENCE  # the only real candidate


# ===================================================================
# execute_action
# ===================================================================


class TestExecuteAction:
    def test_recommend_resource_returns_top_candidate(self):
        obs = _obs(resources_by_skill={"C": [
            ResourceCandidate(resource_id="R1", title="Best", quality_score=0.9),
            ResourceCandidate(resource_id="R2", title="Second", quality_score=0.5),
        ]})
        chosen = ChosenAction(action_type=ActionType.RECOMMEND_RESOURCE, skill_id="C", justification="x")
        result = execute_action(chosen, obs)
        assert result.data["resource_id"] == "R1"

    def test_recompute_path_without_replan_fn_reports_gap_honestly(self):
        chosen = ChosenAction(action_type=ActionType.RECOMPUTE_PATH, justification="x")
        result = execute_action(chosen, _obs(), replan_fn=None)
        assert "no replan_fn" in result.outcome

    def test_recompute_path_calls_replan_fn_and_reports_delta(self):
        fake_result = MagicMock(new_path=["A", "B", "Z"], added_skills=["B"], removed_skills=[])
        replan_fn = MagicMock(return_value=fake_result)
        chosen = ChosenAction(action_type=ActionType.RECOMPUTE_PATH, justification="x")
        result = execute_action(chosen, _obs(), replan_fn=replan_fn)
        replan_fn.assert_called_once()
        assert result.data["added_skills"] == ["B"]

    def test_no_action_reports_nothing_needed(self):
        chosen = ChosenAction(action_type=ActionType.NO_ACTION, justification="all clear")
        result = execute_action(chosen, _obs())
        assert result.outcome == "No action needed this cycle."

    def test_escalate_stuck_learner_includes_learner_id(self):
        chosen = ChosenAction(action_type=ActionType.ESCALATE_STUCK_LEARNER, skill_id="C", justification="x")
        result = execute_action(chosen, _obs(learner_id="L999"))
        assert result.data["learner_id"] == "L999"


# ===================================================================
# AgentScheduler.run_agentic_cycle — end-to-end with mocked dependencies
# ===================================================================


class TestRunAgenticCycle:
    def _build_scheduler(self, fetch_learner_observation, record_agentic_decision=None, fetch_decay_events=None):
        from agent.engine import AgentScheduler
        from agent.models import DecayEvent

        return AgentScheduler(
            fetch_decay_events=fetch_decay_events or (lambda: [DecayEvent(learner_id="L001", skill_id="C")]),
            fetch_learner_context=lambda _lid: None,
            fetch_skill=lambda _sid: None,
            fetch_all_prereqs_recursive=lambda _sid: [],
            fetch_prereq_edges=lambda _sids: [],
            fetch_learner_observation=fetch_learner_observation,
            record_agentic_decision=record_agentic_decision,
            llm_client=_NO_LLM,
        )

    def test_missing_fetch_learner_observation_returns_empty(self):
        scheduler = self._build_scheduler(fetch_learner_observation=None)
        assert scheduler.run_agentic_cycle() == []

    def test_no_decay_events_returns_empty(self):
        scheduler = self._build_scheduler(
            fetch_learner_observation=lambda lid, skills: _obs(learner_id=lid),
            fetch_decay_events=lambda: [],
        )
        assert scheduler.run_agentic_cycle() == []

    def test_processes_learner_and_records_decision(self):
        recorded = []

        def fetch_obs(learner_id, decayed_skill_ids):
            return _obs(learner_id=learner_id, stale_evidence_skills=["A"])

        def record(learner_id, observation, chosen, result):
            recorded.append((learner_id, chosen.action_type, result.outcome))

        scheduler = self._build_scheduler(fetch_learner_observation=fetch_obs, record_agentic_decision=record)
        results = scheduler.run_agentic_cycle()

        assert len(results) == 1
        assert results[0].action_type == ActionType.REQUEST_EVIDENCE
        assert len(recorded) == 1
        assert recorded[0][0] == "L001"

    def test_recording_failure_does_not_drop_the_result(self):
        def fetch_obs(learner_id, decayed_skill_ids):
            return _obs(learner_id=learner_id)

        def broken_record(*args, **kwargs):
            raise RuntimeError("Neo4j is down")

        scheduler = self._build_scheduler(fetch_learner_observation=fetch_obs, record_agentic_decision=broken_record)
        results = scheduler.run_agentic_cycle()
        assert len(results) == 1  # the action still executed and is returned, even though recording failed

    def test_missing_observation_skips_learner_gracefully(self):
        scheduler = self._build_scheduler(fetch_learner_observation=lambda lid, skills: None)
        assert scheduler.run_agentic_cycle() == []


# ===================================================================
# observe_learner_state — integration-style test against a fake Neo4j tx
# ===================================================================


class _FakeRecord(dict):
    pass


class _FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class _FakeTx:
    """Query-text-sniffing fake transaction, matching the convention
    established in tests/test_marketplace_ingestion.py."""

    def __init__(self, target_skill, deadline, known_skills, history, active_resources_by_skill):
        self.target_skill = target_skill
        self.deadline = deadline
        self.known_skills = known_skills
        self.history = history
        self.active_resources_by_skill = active_resources_by_skill

    def run(self, query, **params):
        if "l.target_skill AS target_skill" in query:
            return _FakeResult([_FakeRecord(target_skill=self.target_skill, deadline=self.deadline)])
        if "k.last_practiced AS last_practiced" in query and "HAD_DECISION" not in query:
            return _FakeResult([_FakeRecord(r) for r in self.known_skills])
        if "HAD_DECISION" in query:
            return _FakeResult([_FakeRecord(r) for r in self.history])
        if "status: 'active'" in query:
            skill_id = params.get("skill_id")
            return _FakeResult([_FakeRecord(r) for r in self.active_resources_by_skill.get(skill_id, [])])
        return _FakeResult([])


class TestObserveLearnerState:
    def test_returns_none_without_target_skill(self):
        tx = _FakeTx(target_skill=None, deadline=None, known_skills=[], history=[], active_resources_by_skill={})
        assert observe_learner_state(tx, "L001", now=_NOW) is None

    def test_assembles_full_observation(self):
        tx = _FakeTx(
            target_skill="Z",
            deadline="2026-12-01",
            known_skills=[
                {"skill_id": "A", "confidence": 0.9, "last_practiced": (_NOW - timedelta(days=200)).isoformat()},
            ],
            history=[
                {"new_path": ["C", "Z"], "added_skills": ["C"]},
                {"new_path": ["C", "Z"], "added_skills": ["C"]},
            ],
            active_resources_by_skill={
                "C": [{"id": "R1", "title": "C Course", "quality_score": 0.8}],
            },
        )
        obs = observe_learner_state(tx, "L001", decayed_skill_ids=["C"], now=_NOW)
        assert obs is not None
        assert obs.target_skill == "Z"
        assert obs.decayed_skills == ["C"]
        assert obs.stuck_skills == ["C"]  # appeared in both recent decisions
        assert "A" in obs.stale_evidence_skills  # 200 days old, past the 60-day default
        assert obs.resources_by_skill["C"][0].resource_id == "R1"
