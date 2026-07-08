from unittest.mock import MagicMock, patch
from backend.agent.scheduler import AgentScheduler
from backend.agent.models import DecayEvent


@patch("backend.agent.scheduler.process_decay_events")
def test_scheduler_run_now_with_events(mock_process):
    """
    Test that the scheduler triggers the proactive agent when events exist.
    """
    # Mocking Person A's scanner
    events = [DecayEvent(learner_id="L001", skill_id="SKILL_A")]
    mock_fetch_events = MagicMock(return_value=events)
    
    mock_process.return_value = ["NARRATED_DECISION"]
    
    scheduler = AgentScheduler(
        fetch_decay_events=mock_fetch_events,
        fetch_learner_context=MagicMock(),
        fetch_skill=MagicMock(),
        fetch_all_prereqs_recursive=MagicMock(),
        fetch_prereq_edges=MagicMock()
    )
    
    results = scheduler.run_now()
    
    assert len(results) == 1
    assert results[0] == "NARRATED_DECISION"
    mock_fetch_events.assert_called_once()
    mock_process.assert_called_once()


@patch("backend.agent.scheduler.process_decay_events")
def test_scheduler_run_now_no_events(mock_process):
    """
    Test that the scheduler safely aborts and does not trigger the 
    proactive agent if no events are returned from Person A's scanner.
    """
    mock_fetch_events = MagicMock(return_value=[])
    
    scheduler = AgentScheduler(
        fetch_decay_events=mock_fetch_events,
        fetch_learner_context=MagicMock(),
        fetch_skill=MagicMock(),
        fetch_all_prereqs_recursive=MagicMock(),
        fetch_prereq_edges=MagicMock()
    )
    
    results = scheduler.run_now()
    
    assert len(results) == 0
    mock_fetch_events.assert_called_once()
    mock_process.assert_not_called()
