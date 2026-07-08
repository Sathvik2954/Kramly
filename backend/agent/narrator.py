import logging
from typing import Optional

import ollama

from .models import PlannerDecision, NarratedDecision

logger = logging.getLogger(__name__)


def generate_narration(decision: PlannerDecision) -> NarratedDecision:
    """
    Generates a natural language explanation for a replanning decision using Ollama.
    Falls back to a deterministic template if Ollama is unavailable.
    """
    prompt = f"""
    You are an AI learning path advisor. A learner's path has just been updated because their skill retention decayed.
    
    Here are the details:
    - Learner ID: {decision.learner_id}
    - Trigger: {decision.trigger_type}
    - Removed Skills: {', '.join(decision.removed_skills) if decision.removed_skills else 'None'}
    - Added Skills: {', '.join(decision.added_skills) if decision.added_skills else 'None'}
    - Old Path: {', '.join(decision.old_path)}
    - New Path: {', '.join(decision.new_path)}

    Please explain:
    1. Why replanning happened.
    2. Which skills changed.
    3. Why those skills were added.
    4. What the learner should study next (based on the new path).
    
    Keep the explanation concise, encouraging, and under 4 sentences.
    """

    natural_language_reason = _fallback_explanation(decision)

    try:
        # Assuming 'llama3' is the default model available in the environment.
        response = ollama.chat(model='llama3', messages=[
            {
                'role': 'system',
                'content': 'You are a helpful, concise learning path advisor.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ])
        
        if response and 'message' in response and 'content' in response['message']:
            natural_language_reason = response['message']['content'].strip()
            logger.info("Successfully generated narration using Ollama.")
            
    except Exception as e:
        logger.warning(f"Ollama unavailable or failed ({e}). Falling back to deterministic template.")
        # Fallback is already set

    return NarratedDecision(
        planner_decision=decision,
        natural_language_reason=natural_language_reason
    )


def _fallback_explanation(decision: PlannerDecision) -> str:
    """
    Provides a deterministic explanation if the LLM is unavailable.
    """
    added = ", ".join(decision.added_skills) if decision.added_skills else "no new skills"
    removed = ", ".join(decision.removed_skills) if decision.removed_skills else "no skills"
    next_skill = decision.new_path[0] if decision.new_path else "general review"

    return (
        f"Replanning was triggered due to {decision.trigger_type}. "
        f"We updated your learning path by removing {removed} and adding {added} to strengthen your fundamentals. "
        f"You should start by studying {next_skill} next to get back on track."
    )
