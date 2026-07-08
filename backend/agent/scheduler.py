import logging
from typing import Callable, List, Optional, Dict, Any

from .models import DecayEvent, NarratedDecision
from .proactive_agent import process_decay_events

logger = logging.getLogger(__name__)

# Callables that inject dependencies from the graph and Person A's scanner
FetchDecayEvents = Callable[[], List[DecayEvent]]
FetchLearnerContext = Callable[[str], Optional[Dict[str, Any]]]
FetchSkill = Callable[[str], Optional[dict]]
FetchAllPrereqsRecursive = Callable[[str], list[dict]]
FetchPrereqEdges = Callable[[list[str]], list[tuple[str, str]]]


class AgentScheduler:
    """
    Abstracts scheduling and orchestration for the proactive agent.
    
    This class is designed as an interface so that a concrete background 
    job scheduler (like APScheduler, Celery, or cron) can be seamlessly 
    plugged in later without altering business logic.
    """
    
    def __init__(
        self,
        fetch_decay_events: FetchDecayEvents,
        fetch_learner_context: FetchLearnerContext,
        fetch_skill: FetchSkill,
        fetch_all_prereqs_recursive: FetchAllPrereqsRecursive,
        fetch_prereq_edges: FetchPrereqEdges
    ):
        self.fetch_decay_events = fetch_decay_events
        self.fetch_learner_context = fetch_learner_context
        self.fetch_skill = fetch_skill
        self.fetch_all_prereqs_recursive = fetch_all_prereqs_recursive
        self.fetch_prereq_edges = fetch_prereq_edges
        self._is_running = False

    def run_now(self) -> List[NarratedDecision]:
        """
        Manually triggers the agent's decay processing workflow immediately.
        Useful for API endpoints or manual overrides.
        """
        logger.info("Executing proactive agent workflow manually.")
        try:
            # 1. Receive decay events (from Person A's logic)
            events = self.fetch_decay_events()
            
            if not events:
                logger.info("No decay events found. Agent run terminating early.")
                return []
                
            logger.info(f"Retrieved {len(events)} decay events. Triggering Proactive Agent.")
            
            # 2. Trigger Proactive Agent
            results = process_decay_events(
                events=events,
                fetch_learner_context=self.fetch_learner_context,
                fetch_skill=self.fetch_skill,
                fetch_all_prereqs_recursive=self.fetch_all_prereqs_recursive,
                fetch_prereq_edges=self.fetch_prereq_edges
            )
            
            logger.info(f"Agent workflow completed. Processed {len(results)} events.")
            return results
            
        except Exception as e:
            logger.error(f"Critical error during agent workflow execution: {e}", exc_info=True)
            return []

    def start_scheduler(self):
        """
        Starts the background scheduler. 
        (Implementation placeholder for APScheduler/Cron)
        """
        self._is_running = True
        logger.info("Scheduler started. (Note: Using placeholder scheduler backend)")
        # In a real implementation, we would register `self.run_now` with a cron expression here.

    def stop_scheduler(self):
        """
        Stops the background scheduler.
        """
        self._is_running = False
        logger.info("Scheduler stopped.")
