"""
test_replanning.py
------------------
Tests the core replanning orchestrator and trigger engine.

Design decisions
~~~~~~~~~~~~~~~~
1. **Mocking the Planner**:
   We use `unittest.mock.patch` to mock `generate_learning_path`. We don't want to
   test the graph traversal algorithm here (that's already covered in `test_planner.py`).
   We only want to test that the replanner *calls* it correctly, handles the events,
   and computes the correct diff (added/removed skills).

2. **Idempotency Assertions**:
   We use the `check_idempotency` utility to assert that executing the replanner
   twice with the identical inputs produces functionally identical results.

3. **No Database**:
   All dependencies injected into `replan_learning_path` (`fetch_skill`, etc.) are
   dummy lambdas, guaranteeing these tests execute entirely offline in milliseconds.
"""

import pytest
from unittest.mock import patch, MagicMock

from agent.event_types import (
    QuizCompleted, DeadlineChanged, TargetChanged, ManualReplanRequested, BaseEvent
)
from agent.replanner import replan_learning_path
from agent.idempotency import check_idempotency

# Dummy dependencies to satisfy the injected callables
dummy_fetch = lambda x: None
dummy_fetch_all = lambda x: []
dummy_fetch_edges = lambda x: []

# A generic unknown event to test fall-through logic
class UnknownEvent(BaseEvent):
    pass


@patch("agent.replanner.generate_learning_path")
class TestTriggerEngineAndReplanner:
    """Tests evaluating triggers and orchestrating the replan."""

    def test_quiz_completed_triggers_replanning(self, mock_generate):
        mock_generate.return_value = ["A", "B", "C"]
        event = QuizCompleted(learner_id="1", skill_id="X", passed=True, confidence=0.9)
        
        result = replan_learning_path(
            known_skills=["X"], target_skill="C", current_path=["A", "B"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        
        assert result is not None
        mock_generate.assert_called_once()

    def test_deadline_changed_triggers_replanning(self, mock_generate):
        mock_generate.return_value = ["A", "B"]
        event = DeadlineChanged(learner_id="1", target_skill_id="B", new_deadline="tomorrow")
        
        result = replan_learning_path(
            known_skills=[], target_skill="B", current_path=["A", "B"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        assert result is not None

    def test_target_changed_triggers_replanning(self, mock_generate):
        mock_generate.return_value = ["X", "Y"]
        event = TargetChanged(learner_id="1", new_target_skill_id="Y")
        
        result = replan_learning_path(
            known_skills=[], target_skill="Y", current_path=["A", "B"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        assert result is not None

    def test_unknown_event_ignored(self, mock_generate):
        event = UnknownEvent(learner_id="1")
        
        result = replan_learning_path(
            known_skills=[], target_skill="B", current_path=["A", "B"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        
        assert result is None
        mock_generate.assert_not_called()

    def test_added_and_removed_skills_detected_correctly(self, mock_generate):
        # Old path: A, B, C
        # New path: B, C, D (A is removed, D is added)
        mock_generate.return_value = ["B", "C", "D"]
        event = ManualReplanRequested(learner_id="1")
        
        result = replan_learning_path(
            known_skills=["A"], target_skill="D", current_path=["A", "B", "C"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        
        assert result.added_skills == ["D"]
        assert result.removed_skills == ["A"]

    def test_idempotency_of_replanner(self, mock_generate):
        mock_generate.return_value = ["X", "Y", "Z"]
        event = ManualReplanRequested(learner_id="1")
        kwargs = dict(
            known_skills=[], target_skill="Z", current_path=["W"], event=event,
            fetch_skill=dummy_fetch, fetch_all_prereqs_recursive=dummy_fetch_all, fetch_prereq_edges=dummy_fetch_edges
        )
        
        # Execute twice with identical inputs
        first_result = replan_learning_path(**kwargs)
        second_result = replan_learning_path(**kwargs)
        
        assert check_idempotency(first_result, second_result) is True
        
        # Ensure the planner was called exactly twice (once per execution)
        assert mock_generate.call_count == 2
