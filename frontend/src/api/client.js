/**
 * client.js
 * Thin fetch wrapper for talking to the Kramly backend.
 *
 * ASSUMPTION FLAG: I don't have your actual backend/models/request.py and
 * response.py field names — only the file-role description from
 * project_structure.md. The field names below (known_skills, target_skill,
 * ordered_path) are my best guess at a reasonable contract, NOT confirmed
 * against your real Pydantic models. Confirm with your teammate and adjust
 * this file if the real field names differ.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function fetchLearningPath({ learnerId, knownSkills, targetSkill }) {
  const response = await fetch(`${API_BASE_URL}/learning-path`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      learner_id: learnerId,
      known_skills: knownSkills,
      target_skill: targetSkill,
    }),
  });

  if (!response.ok) {
    // ASSUMPTION FLAG: error shape based on your described 404/409 mapping
    // in routes.py — actual error body format not confirmed.
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || `Request failed with status ${response.status}`);
  }

  return response.json();
}

/**
 * NOTE: this endpoint does not exist yet in your backend per
 * project_structure.md — routes.py currently only has POST /learning-path.
 * This is Person B's Phase 2 decision-logging work to add. The frontend
 * call below will fail (404) until that endpoint is built.
 */
export async function fetchDecisionLogHistory(learnerId) {
  const response = await fetch(`${API_BASE_URL}/decision-log/${learnerId}`);
  if (!response.ok) {
    throw new Error(`Decision log request failed with status ${response.status}`);
  }
  return response.json();
}

/**
 * NOTE: also not yet a confirmed existing endpoint. Needed to fetch the
 * full skill graph (nodes + edges) for the visualization component.
 * You may already have something like this, or need to add it to routes.py.
 */
export async function fetchSkillGraph(domain) {
  const url = domain ? `${API_BASE_URL}/graph?domain=${domain}` : `${API_BASE_URL}/graph`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Graph fetch failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchLearnerState(learnerId) {
  const response = await fetch(`${API_BASE_URL}/learner/${learnerId}`);
  if (!response.ok) {
    if (response.status === 404) return null;
    throw new Error(`Learner state fetch failed with status ${response.status}`);
  }
  return response.json();
}

export async function recordLearnerEvidence(learnerId, { skillId, confidence }) {
  const response = await fetch(`${API_BASE_URL}/learner/${learnerId}/evidence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      skill_id: skillId,
      confidence: parseFloat(confidence),
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || `Failed to record evidence: ${response.status}`);
  }

  return response.json();
}

export async function setLearnerTarget(learnerId, { targetSkill, deadline }) {
  const response = await fetch(`${API_BASE_URL}/learner/${learnerId}/target`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_skill: targetSkill,
      deadline: deadline || null,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || `Failed to set target: ${response.status}`);
  }

  return response.json();
}
