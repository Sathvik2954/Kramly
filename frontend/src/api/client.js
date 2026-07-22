/**
 * client.js
 * Thin fetch wrapper for talking to the Kramly backend.
 *
 * API contract (confirmed against models/request.py and models/response.py):
 *   POST /learning-path        → { known_skills, target_skill } → { path: string[] }
 *   GET  /decision-log/:id     → DecisionLogEntry[]
 *   GET  /agentic-decision-log/:id → AgenticDecision[] (observe-reason-act trace)
 *   GET  /graph                → { nodes: [{id, name, domain}], links: [{source, target}] }
 *   GET  /learner/:id          → { learner_id, target_skill, deadline, known_skills }
 *   POST /learner/:id/evidence → { skill_id, confidence } → { status, message }
 *   POST /learner/:id/target   → { target_skill, deadline? } → { status, message }
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
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || `Request failed with status ${response.status}`);
  }

  return response.json();
}

export async function fetchDecisionLogHistory(learnerId) {
  const response = await fetch(`${API_BASE_URL}/decision-log/${learnerId}`);
  if (!response.ok) {
    throw new Error(`Decision log request failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchAgenticDecisionLog(learnerId) {
  const response = await fetch(`${API_BASE_URL}/agentic-decision-log/${learnerId}`);
  if (!response.ok) {
    throw new Error(`Agentic decision log request failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchSkillGraph(domain) {
  const url = domain ? `${API_BASE_URL}/graph?domain=${domain}` : `${API_BASE_URL}/graph`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Graph fetch failed with status ${response.status}`);
  }
  return response.json();
}

export async function fetchDomains() {
  const response = await fetch(`${API_BASE_URL}/domains`);
  if (!response.ok) {
    throw new Error(`Domain list fetch failed with status ${response.status}`);
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

export async function fetchMarketplaceRecommendations(skillId) {
  const response = await fetch(`${API_BASE_URL}/marketplace/resources?skill_id=${skillId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch recommendations: ${response.status}`);
  }
  return response.json();
}

export async function fetchResourceDetails(resourceId) {
  const response = await fetch(`${API_BASE_URL}/marketplace/resource/${resourceId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch resource details: ${response.status}`);
  }
  return response.json();
}

export async function uploadResource({ title, author, description, coveredSkills, content }) {
  const formData = new FormData();
  formData.append("title", title);
  formData.append("author", author);
  formData.append("description", description || "");
  formData.append("covered_skills", JSON.stringify(coveredSkills));
  
  const blob = new Blob([content], { type: "text/plain" });
  formData.append("file", blob, "resource.txt");

  const response = await fetch(`${API_BASE_URL}/marketplace/resource`, {
    method: "POST",
    body: formData
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || `Upload failed: ${response.status}`);
  }

  return response.json();
}

export async function rateResource(resourceId, authorId, rating) {
  const response = await fetch(`${API_BASE_URL}/marketplace/resource/${resourceId}/rate?author_id=${authorId}&rating=${rating}`, {
    method: "POST"
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || errorBody.message || "Failed to submit rating.");
  }
  return response.json();
}

export async function supersedeResource(oldResourceId, newResourceId) {
  const response = await fetch(`${API_BASE_URL}/marketplace/resource/${oldResourceId}/supersede?new_resource_id=${newResourceId}`, {
    method: "POST"
  });
  if (!response.ok) {
    throw new Error("Failed to supersede resource.");
  }
  return response.json();
}

export async function fetchResourceHistory(resourceId) {
  const response = await fetch(`${API_BASE_URL}/marketplace/resource/${resourceId}/history`);
  if (!response.ok) {
    throw new Error("Failed to fetch resource history.");
  }
  return response.json();
}

