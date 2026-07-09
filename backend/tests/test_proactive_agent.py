from unittest.mock import patch, MagicMock

from backend.agent.models import DecayEvent
from backend.agent.proactive_agent import process_decay_events, DecayThresholdCrossed


@patch("backend.agent.proactive_agent.generate_narration")
@patch("backend.agent.proactive_agent.should_replan")
@patch("backend.agent.proactive_agent.replan_learning_path")
@patch("backend.agent.proactive_agent.log_decision")
def test_process_decay_events_full_flow(
    mock_log, mock_replan, mock_should_replan, mock_generate_narration
):
    """
    Test that the proactive agent orchestrates the entire workflow correctly.
    """
    # 1. Setup Dummy Data
    events = [
        DecayEvent(learner_id="L001", skill_id="SKILL_A", trigger_type="DecayThresholdCrossed"),
        DecayEvent(learner_id="L002", skill_id="SKILL_B", trigger_type="DecayThresholdCrossed")
    ]
    
    # 2. Setup Mocks
    mock_should_replan.side_effect = [True, False] # Replan for L001, skip for L002
    
    # Mocking the replan_learning_path result for L001
    mock_result = MagicMock()
    mock_result.old_path = ["SKILL_X"]
    mock_result.new_path = ["SKILL_Y"]
    mock_result.added_skills = ["SKILL_Y"]
    mock_result.removed_skills = ["SKILL_X"]
    mock_result.reason = "Decayed"
    mock_replan.return_value = mock_result
    
    # Mocking context fetcher
    def dummy_fetch_context(learner_id):
        return {"known_skills": [], "target_skill": "GOAL", "current_path": ["SKILL_X"]}
    
    # 3. Execute Workflow
    results = process_decay_events(
        events=events,
        fetch_learner_context=dummy_fetch_context,
        fetch_skill=MagicMock(),
        fetch_all_prereqs_recursive=MagicMock(),
        fetch_prereq_edges=MagicMock()
    )
    
    # 4. Assertions
    # Only 1 result because L002 was skipped by should_replan
    assert len(results) == 1
    
    # Verify should_replan was called twice, and trigger_event mapping worked
    assert mock_should_replan.call_count == 2
    args_call_1 = mock_should_replan.call_args_list[0][0][0]
    assert isinstance(args_call_1, DecayThresholdCrossed)
    assert args_call_1.learner_id == "L001"
    
    # Verify replan was invoked exactly once
    mock_replan.assert_called_once()
    
    # Verify narrator was invoked exactly once
    mock_generate_narration.assert_called_once()
    
    # Verify decision logger was invoked exactly once with the required args
    mock_log.assert_called_once()
    logged_event = mock_log.call_args[1]["event"]
    assert isinstance(logged_event, DecayThresholdCrossed)
    assert "execution_time_ms" in mock_log.call_args[1]
