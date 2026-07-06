"""
audit_logger.py
---------------
Maintains a strict, structured audit trail for the governance layer.

Design decisions
~~~~~~~~~~~~~~~~
1. **Compliance Ready**:
   In any human-in-the-loop system, knowing *who* approved *what* and *when* 
   is critical. This logger ensures every single state transition (PENDING -> 
   APPROVED, APPROVED -> MERGED) is explicitly recorded.
2. **Dual-Output Architecture**:
   Similar to the decision logger from Phase 2, this module writes a JSON 
   string to standard Python logging (for Datadog/Splunk) while returning 
   a Pydantic object for internal API usage and strict unit testing.
3. **Decoupled**:
   This module doesn't enforce business logic. It simply accepts state transition 
   data and logs it. It relies on the caller (`review_service` or `merge_service`) 
   to provide accurate 'old_status' and 'new_status' values.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditLogEntry(BaseModel):
    """Structured record of an action taken within the review governance layer."""
    timestamp: str = Field(..., description="ISO 8601 timestamp of the action.")
    actor: str = Field(..., description="The identity of the user/system performing the action.")
    candidate_id: str = Field(..., description="The ID of the candidate edge affected.")
    old_status: Optional[str] = Field(None, description="The status of the candidate before the action.")
    new_status: str = Field(..., description="The status of the candidate after the action.")
    reason: str = Field(..., description="Context or justification for the action.")


def log_audit_action(
    actor: str,
    candidate_id: str,
    old_status: Optional[str],
    new_status: str,
    reason: str
) -> AuditLogEntry:
    """Records a state transition or significant event in the review system.
    
    Args:
        actor (str): The identity of the human reviewer or system component.
        candidate_id (str): The edge candidate being operated on.
        old_status (Optional[str]): The state before this action occurred.
        new_status (str): The state resulting from this action.
        reason (str): Why this action occurred (e.g., 'Approved by SME', 'Cycle detected').
        
    Returns:
        AuditLogEntry: A structured object representing the log entry.
    """
    entry = AuditLogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor=actor,
        candidate_id=candidate_id,
        old_status=old_status,
        new_status=new_status,
        reason=reason
    )

    # Dump to JSON so it is easily parseable by centralized logging systems
    log_payload = entry.model_dump()
    logger.info("REVIEW AUDIT LOG: %s", json.dumps(log_payload))

    return entry
