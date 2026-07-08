from unittest.mock import patch

from backend.agent.models import PlannerDecision
from backend.agent.narrator import generate_narration, _fallback_explanation

# Dummy decision for testing
dummy_decision = PlannerDecision(
    learner_id="L001",
    old_path=["SKILL_1", "SKILL_2"],
    new_path=["SKILL_3", "SKILL_2"],
    added_skills=["SKILL_3"],
    removed_skills=["SKILL_1"],
    trigger_type="DecayThresholdCrossed",
    reason="Replanned due to DecayThresholdCrossed"
)


@patch("backend.agent.narrator.ollama.chat")
def test_narrator_generates_explanation_success(mock_chat):
    """
    Test that the narrator correctly uses Ollama to generate an explanation
    when the API is available.
    """
    # Mock a successful response from Ollama
    mock_chat.return_value = {
        'message': {
            'role': 'assistant',
            'content': 'This is a mocked LLM explanation.'
        }
    }
    
    narrated = generate_narration(dummy_decision)
    
    assert narrated.planner_decision == dummy_decision
    assert narrated.natural_language_reason == 'This is a mocked LLM explanation.'
    mock_chat.assert_called_once()


@patch("backend.agent.narrator.ollama.chat")
def test_narrator_fallback_explanation(mock_chat):
    """
    Test that the narrator gracefully degrades to the deterministic
    template if Ollama throws an exception.
    """
    # Force Ollama to throw an exception
    mock_chat.side_effect = Exception("Ollama server down")
    
    narrated = generate_narration(dummy_decision)
    
    assert narrated.planner_decision == dummy_decision
    assert "Replanning was triggered due to DecayThresholdCrossed." in narrated.natural_language_reason
    assert "SKILL_1" in narrated.natural_language_reason
    assert "SKILL_3" in narrated.natural_language_reason
    
    expected_fallback = _fallback_explanation(dummy_decision)
    assert narrated.natural_language_reason == expected_fallback
