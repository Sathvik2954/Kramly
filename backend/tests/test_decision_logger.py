"""
test_decision_logger.py
-----------------------
Tests the decision logger logic and output.

Design decisions
~~~~~~~~~~~~~~~~
1. **Mocking Python Logger**:
   We use `patch` on `agent.decision_logger.logger.info` to verify that the
   expected JSON payload is actually sent to the underlying logging system.
   This ensures we don't accidentally break our system-level observability.

2. **Validating the Return Object**:
   We verify that the function returns a properly hydrated `DecisionLogEntry`
   Pydantic model that the API layer can consume directly.
"""

import json
from unittest.mock import patch
from agent.decision_logger import log_decision, DecisionLogEntry
from agent.event_types import ManualReplanRequested
from agent.replanner import ReplanningResult


def test_decision_log_generated_and_returned():
    # Setup dummy data
    event = ManualReplanRequested(learner_id="test_user_1", reason="User clicked button")
    result = ReplanningResult(
        old_path=["A", "B", "C"],
        new_path=["C", "D"],
        added_skills=["D"],
        removed_skills=["A", "B"],
        reason="Replanned due to ManualReplanRequested",
        timestamp="2024-01-01T12:00:00Z"
    )
    execution_time = 15.5

    # Mock the internal Python logger to spy on what gets written to stdout/file
    with patch("agent.decision_logger.logger.info") as mock_logger:
        log_entry = log_decision(event, result, execution_time)

        # 1. Verify a Pydantic object is returned
        assert isinstance(log_entry, DecisionLogEntry)
        assert log_entry.learner_id == "test_user_1"
        assert log_entry.event_type == "ManualReplanRequested"
        assert log_entry.added_skills == ["D"]
        assert log_entry.execution_time_ms == 15.5

        # 2. Verify it actually wrote the JSON string to the python logger
        mock_logger.assert_called_once()
        log_message = mock_logger.call_args[0][1] # Get the JSON string passed to logger.info
        
        # Parse it back to ensure valid JSON
        parsed_log = json.loads(log_message)
        assert parsed_log["learner_id"] == "test_user_1"
        assert parsed_log["removed_skills"] == ["A", "B"]
