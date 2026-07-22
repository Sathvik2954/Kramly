"""
test_engine.py
---------------
Tests for the agent orchestration core (trigger judgment, replanning,
proactive decay processing, scheduler, decision logging, idempotency).

Consolidated from the former test_replanning.py + test_proactive_agent.py +
test_scheduler.py + test_decision_logger.py.

Design decisions
~~~~~~~~~~~~~~~~
1. **Deterministic-fallback tests use a bare `LLMClient()`.**
   With no API keys configured, `has_any_provider` is False and
   `llm_should_replan` transparently uses `_fallback_should_replan` — the
   same isinstance-based rule the old trigger_engine.py used. This lets
   most tests run fully offline while still exercising real code (not
   mocks) for the "no LLM available" path, which is the safety net this
   whole design depends on.
2. **A handful of tests mock `LLMClient.complete_json` directly** to prove
   the LLM's judgment is actually consulted and honored when a provider
   IS configured — including cases where it disagrees with what the old
   deterministic rule would have said. That's the behavioral difference
   this rewrite is for.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_client import LLMClient
from agent.models import (
    BaseEvent,
    DecayEvent,
    DeadlineChanged,
    ManualReplanRequested,
    QuizCompleted,
    TargetChanged,
)
from agent.engine import (
    AgentScheduler,
    DecayThresholdCrossed,
    check_idempotency,
    llm_should_replan,
    log_decision,
    process_decay_events,
    replan_learning_path,
)

# No-provider client: forces the deterministic fallback path everywhere below.
_NO_LLM = LLMClient()

dummy_fetch = lambda x: None
dummy_fetch_all = lambda x: []
dummy_fetch_edges = lambda x: []


class UnknownEvent(BaseEvent):
    pass


# ===================================================================
# TRIGGER JUDGMENT — deterministic fallback (no LLM configured)
# ===================================================================


class TestFallbackTriggerJudgment:
    """With no LLM provider configured, judgment falls back to the old rule set."""

    def test_known_event_types_trigger_replan(self):
        for event in [
            QuizCompleted(learner_id="1", skill_id="X", passed=True, confidence=0.9),
            DeadlineChanged(learner_id="1", target_skill_id="B", new_deadline="tomorrow"),
            TargetChanged(learner_id="1", new_target_skill_id="Y"),
            ManualReplanRequested(learner_id="1"),
        ]:
            should, reasoning = llm_should_replan(
                event, known_skills=[], target_skill="B", current_path=[], llm_client=_NO_LLM
            )
            assert should is True
            assert "fallback" in reasoning

    def test_unknown_event_does_not_trigger_replan(self):
        should, reasoning = llm_should_replan(
            UnknownEvent(learner_id="1"), known_skills=[], target_skill="B", current_path=[], llm_client=_NO_LLM
        )
        assert should is False
        assert "fallback" in reasoning


# ===================================================================
# TRIGGER JUDGMENT — LLM-driven (provider configured, mocked network)
# ===================================================================


class TestLLMTriggerJudgment:
    """With a provider configured, the LLM's decision is what's honored."""

    @patch("agent.llm_client.httpx.post")
    def test_llm_can_approve_replan(self, mock_post):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"should_replan": True, "reasoning": "target changed"})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        should, reasoning = llm_should_replan(
            ManualReplanRequested(learner_id="1"),
            known_skills=[], target_skill="B", current_path=[], llm_client=client,
        )
        assert should is True
        assert reasoning == "target changed"

    @patch("agent.llm_client.httpx.post")
    def test_llm_can_reject_replan_even_for_a_legacy_trigger_type(self, mock_post):
        """The old deterministic rule always replanned on QuizCompleted; the LLM can decide otherwise."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"should_replan": False, "reasoning": "irrelevant skill"})}}]
        }
        mock_post.return_value = resp
        client = LLMClient(groq_api_key="gk")

        should, reasoning = llm_should_replan(
            QuizCompleted(learner_id="1", skill_id="unrelated", passed=True, confidence=0.99),
            known_skills=[], target_skill="B", current_path=["B"], llm_client=client,
        )
        assert should is False
        assert reasoning == "irrelevant skill"


# ===================================================================
# REPLANNER
# ===================================================================


@patch("agent.engine.generate_learning_path")
class TestReplanLearningPath:
    def test_quiz_completed_triggers_replanning(self, mock_generate):
        mock_generate.return_value = ["A", "B", "C"]
        event = QuizCompleted(learner_id="1", skill_id="X", passed=True, confidence=0.9)

        result = replan_learning_path(
            known_skills=["X"], target_skill="C", current_path=["A", "B"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all,
            fetch_prereq_edges=dummy_fetch_edges, llm_client=_NO_LLM,
        )
        assert result is not None
        assert result.llm_reasoning  # fallback reasoning is always populated
        mock_generate.assert_called_once()

    def test_unknown_event_ignored(self, mock_generate):
        result = replan_learning_path(
            known_skills=[], target_skill="B", current_path=["A", "B"], event=UnknownEvent(learner_id="1"),
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all,
            fetch_prereq_edges=dummy_fetch_edges, llm_client=_NO_LLM,
        )
        assert result is None
        mock_generate.assert_not_called()

    def test_added_and_removed_skills_detected_correctly(self, mock_generate):
        mock_generate.return_value = ["B", "C", "D"]
        result = replan_learning_path(
            known_skills=["A"], target_skill="D", current_path=["A", "B", "C"],
            event=ManualReplanRequested(learner_id="1"),
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all,
            fetch_prereq_edges=dummy_fetch_edges, llm_client=_NO_LLM,
        )
        assert result.added_skills == ["D"]
        assert result.removed_skills == ["A"]

    def test_idempotency_of_replanner(self, mock_generate):
        mock_generate.return_value = ["X", "Y", "Z"]
        kwargs = dict(
            known_skills=[], target_skill="Z", current_path=["W"], event=ManualReplanRequested(learner_id="1"),
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all,
            fetch_prereq_edges=dummy_fetch_edges, llm_client=_NO_LLM,
        )
        first_result = replan_learning_path(**kwargs)
        second_result = replan_learning_path(**kwargs)
        assert check_idempotency(first_result, second_result) is True
        assert mock_generate.call_count == 2


# ===================================================================
# DECISION LOGGER
# ===================================================================


def test_decision_log_generated_and_returned():
    from agent.models import ReplanningResult

    event = ManualReplanRequested(learner_id="test_user_1", reason="User clicked button")
    result = ReplanningResult(
        old_path=["A", "B", "C"], new_path=["C", "D"], added_skills=["D"], removed_skills=["A", "B"],
        reason="Replanned due to ManualReplanRequested", timestamp="2024-01-01T12:00:00Z",
    )

    with patch("agent.engine.logger.info") as mock_logger:
        log_entry = log_decision(event, result, 15.5)

        assert log_entry.learner_id == "test_user_1"
        assert log_entry.event_type == "ManualReplanRequested"
        assert log_entry.added_skills == ["D"]
        assert log_entry.execution_time_ms == 15.5

        mock_logger.assert_called_once()
        log_message = mock_logger.call_args[0][1]
        parsed_log = json.loads(log_message)
        assert parsed_log["learner_id"] == "test_user_1"
        assert parsed_log["removed_skills"] == ["A", "B"]


# ===================================================================
# PROACTIVE DECAY PROCESSING
# ===================================================================


@patch("agent.engine.generate_narration")
@patch("agent.engine.replan_learning_path")
@patch("agent.engine.log_decision")
def test_process_decay_events_full_flow(mock_log, mock_replan, mock_narrate):
    events = [
        DecayEvent(learner_id="L001", skill_id="SKILL_A", trigger_type="DecayThresholdCrossed"),
        DecayEvent(learner_id="L002", skill_id="SKILL_B", trigger_type="DecayThresholdCrossed"),
    ]

    mock_result = MagicMock()
    mock_result.old_path = ["SKILL_X"]
    mock_result.new_path = ["SKILL_Y"]
    mock_result.added_skills = ["SKILL_Y"]
    mock_result.removed_skills = ["SKILL_X"]
    mock_result.reason = "Decayed"
    # L001 gets a real result, L002 gets None (no replan warranted).
    mock_replan.side_effect = [mock_result, None]

    mock_narration = MagicMock()
    mock_narration.natural_language_reason = "explanation"
    mock_narrate.return_value = mock_narration

    def dummy_fetch_context(learner_id):
        return {"known_skills": [], "target_skill": "GOAL", "current_path": ["SKILL_X"]}

    results = process_decay_events(
        events=events, fetch_learner_context=dummy_fetch_context,
        fetch_skill=MagicMock(), fetch_all_prereqs_recursive=MagicMock(), fetch_prereq_edges=MagicMock(),
        llm_client=_NO_LLM,
    )

    assert len(results) == 1
    assert mock_replan.call_count == 2
    first_call_event = mock_replan.call_args_list[0].kwargs["event"]
    assert isinstance(first_call_event, DecayThresholdCrossed)
    assert first_call_event.learner_id == "L001"
    mock_narrate.assert_called_once()
    mock_log.assert_called_once()


def test_process_decay_events_skips_learner_with_no_context():
    events = [DecayEvent(learner_id="L001", skill_id="SKILL_A")]
    results = process_decay_events(
        events=events, fetch_learner_context=lambda _: None,
        fetch_skill=MagicMock(), fetch_all_prereqs_recursive=MagicMock(), fetch_prereq_edges=MagicMock(),
        llm_client=_NO_LLM,
    )
    assert results == []


# ===================================================================
# SCHEDULER
# ===================================================================


@patch("agent.engine.process_decay_events")
def test_scheduler_run_now_with_events(mock_process):
    events = [DecayEvent(learner_id="L001", skill_id="SKILL_A")]
    mock_fetch_events = MagicMock(return_value=events)
    mock_process.return_value = ["NARRATED_DECISION"]

    scheduler = AgentScheduler(
        fetch_decay_events=mock_fetch_events, fetch_learner_context=MagicMock(),
        fetch_skill=MagicMock(), fetch_all_prereqs_recursive=MagicMock(), fetch_prereq_edges=MagicMock(),
        llm_client=_NO_LLM,
    )
    results = scheduler.run_now()

    assert results == ["NARRATED_DECISION"]
    mock_fetch_events.assert_called_once()
    mock_process.assert_called_once()


@patch("agent.engine.process_decay_events")
def test_scheduler_run_now_no_events(mock_process):
    scheduler = AgentScheduler(
        fetch_decay_events=MagicMock(return_value=[]), fetch_learner_context=MagicMock(),
        fetch_skill=MagicMock(), fetch_all_prereqs_recursive=MagicMock(), fetch_prereq_edges=MagicMock(),
        llm_client=_NO_LLM,
    )
    results = scheduler.run_now()

    assert results == []
    mock_process.assert_not_called()
