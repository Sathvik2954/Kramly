import { useState } from "react";
import { setLearnerTarget, recordLearnerEvidence } from "../api/client";

export default function LearnerConfigForm({ learnerId, onAction, loading }) {
  const [targetSkill, setTargetSkill] = useState("");
  const [deadline, setDeadline] = useState("");
  const [skillId, setSkillId] = useState("");
  const [confidence, setConfidence] = useState(0.8);
  const [statusMessage, setStatusMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [submittingTarget, setSubmittingTarget] = useState(false);
  const [submittingEvidence, setSubmittingEvidence] = useState(false);

  async function handleTargetSubmit(e) {
    e.preventDefault();
    if (!learnerId) {
      setErrorMessage("Enter a Learner ID first.");
      return;
    }
    setSubmittingTarget(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await setLearnerTarget(learnerId, { targetSkill, deadline });
      setStatusMessage(`Successfully set target skill to '${targetSkill}'.`);
      onAction(); // Trigger parent reload/replan
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmittingTarget(false);
    }
  }

  async function handleEvidenceSubmit(e) {
    e.preventDefault();
    if (!learnerId) {
      setErrorMessage("Enter a Learner ID first.");
      return;
    }
    setSubmittingEvidence(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await recordLearnerEvidence(learnerId, { skillId, confidence });
      setStatusMessage(`Recorded evidence for '${skillId}' (Confidence: ${confidence}).`);
      onAction(); // Trigger parent reload/replan
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmittingEvidence(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {statusMessage && (
        <div style={{ padding: "0.75rem", backgroundColor: "var(--accent-success-bg)", border: "var(--border-w) solid var(--border-color)", fontSize: "0.85rem", color: "var(--text-primary)" }}>
          {statusMessage}
        </div>
      )}
      {errorMessage && (
        <div className="error-badge" style={{ marginTop: 0 }}>
          {errorMessage}
        </div>
      )}

      {/* Target Config Form */}
      <form onSubmit={handleTargetSubmit} className="form-container" style={{ borderBottom: "1px solid var(--color-grey-mid)", paddingBottom: "1.5rem" }}>
        <h3 className="section-title" style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>Set Target Profile</h3>

        <div className="input-group">
          <label htmlFor="config-target-input">Target Skill ID</label>
          <input
            id="config-target-input"
            type="text"
            value={targetSkill}
            onChange={(e) => setTargetSkill(e.target.value)}
            placeholder="e.g. WEB010"
            required
            disabled={loading || submittingTarget}
          />
        </div>

        <div className="input-group" style={{ marginTop: "0.75rem" }}>
          <label htmlFor="config-deadline-input">Optional Deadline</label>
          <input
            id="config-deadline-input"
            type="text"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            placeholder="e.g. 2026-12-31"
            disabled={loading || submittingTarget}
          />
        </div>

        <button type="submit" disabled={loading || submittingTarget || !learnerId} style={{ marginTop: "0.75rem" }}>
          {submittingTarget ? "Setting target..." : "Set Target & Replan"}
        </button>
      </form>

      {/* Quiz Evidence Form */}
      <form onSubmit={handleEvidenceSubmit} className="form-container">
        <h3 className="section-title" style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>Record Quiz / Evidence</h3>

        <div className="input-group">
          <label htmlFor="config-skill-input">Practiced Skill ID</label>
          <input
            id="config-skill-input"
            type="text"
            value={skillId}
            onChange={(e) => setSkillId(e.target.value)}
            placeholder="e.g. WEB001"
            required
            disabled={loading || submittingEvidence}
          />
        </div>

        <div className="input-group" style={{ marginTop: "0.75rem" }}>
          <label htmlFor="config-confidence-input">Quiz Score / Confidence: {Number(confidence).toFixed(2)}</label>
          <input
            id="config-confidence-input"
            type="range"
            min="0.0"
            max="1.0"
            step="0.05"
            value={confidence}
            onChange={(e) => setConfidence(parseFloat(e.target.value))}
            style={{ cursor: "pointer" }}
            disabled={loading || submittingEvidence}
          />
        </div>

        <button type="submit" disabled={loading || submittingEvidence || !learnerId} style={{ marginTop: "0.75rem" }}>
          {submittingEvidence ? "Recording..." : "Submit Quiz Evidence"}
        </button>
      </form>
    </div>
  );
}
