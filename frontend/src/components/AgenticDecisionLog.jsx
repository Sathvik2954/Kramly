import { useEffect, useState } from "react";
import { fetchAgenticDecisionLog } from "../api/client";

/**
 * AgenticDecisionLog.jsx
 * Shows the agent's observe-reason-act trace: what it observed about the
 * learner, which action it chose and why, and what executing that action
 * produced. Separate from DecisionLogHistory (which only ever shows a
 * path recompute) because the agent now chooses between several distinct
 * actions - this view is what makes that choice visible.
 * Calls GET /agentic-decision-log/{learnerId} → AgenticDecision[].
 */

const ACTION_LABELS = {
  RECOMPUTE_PATH: "Recomputed path",
  RECOMMEND_RESOURCE: "Recommended a resource",
  FLAG_FOR_REINFORCEMENT: "Flagged for reinforcement",
  REQUEST_EVIDENCE: "Requested fresh evidence",
  ESCALATE_STUCK_LEARNER: "Escalated as stuck",
  NO_ACTION: "No action taken",
};

export default function AgenticDecisionLog({ learnerId }) {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!learnerId) return;
    setLoading(true);
    setError(null);
    fetchAgenticDecisionLog(learnerId)
      .then((data) => setEntries(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [learnerId]);

  if (!learnerId) {
    return <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>Enter a learner ID to view the agentic reasoning trace.</p>;
  }

  if (loading) return <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>Loading reasoning trace...</p>;

  if (error) {
    return (
      <div className="error-badge">
        <strong>Error:</strong> Could not load agentic decision log: {error}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
        No agentic cycles logged yet for this learner. The autonomous scheduler runs this loop on an interval
        (see Settings.decay_scan_interval_minutes) - it only produces entries for learners with a pending decay event.
      </p>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
        Agentic Reasoning Trace for "{learnerId}"
      </h3>
      <ul className="timeline">
        {entries.map((entry, idx) => {
          const actionLabel = ACTION_LABELS[entry.action_type] || entry.action_type || "Unknown action";
          const isLLM = entry.source === "llm";

          let formattedTime = entry.timestamp;
          try {
            if (entry.timestamp && entry.timestamp.includes("T")) {
              formattedTime = new Date(entry.timestamp).toLocaleString();
            }
          } catch (e) {
            // use fallback
          }

          const observed = [
            entry.observed_decayed_skills && entry.observed_decayed_skills.length > 0
              ? `decayed: ${entry.observed_decayed_skills.join(", ")}`
              : null,
            entry.observed_stuck_skills && entry.observed_stuck_skills.length > 0
              ? `stuck: ${entry.observed_stuck_skills.join(", ")}`
              : null,
            entry.observed_stale_evidence_skills && entry.observed_stale_evidence_skills.length > 0
              ? `stale evidence: ${entry.observed_stale_evidence_skills.join(", ")}`
              : null,
          ].filter(Boolean);

          return (
            <li key={idx} className="timeline-item">
              <span className="timeline-marker"></span>
              <span className="timeline-time">
                {formattedTime}
                <span className="timeline-trigger">
                  {actionLabel}
                  {entry.skill_id ? ` (${entry.skill_id})` : ""}
                </span>
              </span>

              <div
                style={{
                  display: "inline-block",
                  marginTop: "0.35rem",
                  marginBottom: "0.35rem",
                  fontSize: "0.7rem",
                  fontFamily: "var(--font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  padding: "0.1rem 0.4rem",
                  borderRadius: "2px",
                  color: isLLM ? "var(--accent-primary)" : "var(--text-muted)",
                  border: `1px solid ${isLLM ? "var(--accent-primary)" : "var(--text-muted)"}`,
                }}
              >
                {isLLM ? "LLM decision" : "deterministic fallback"}
              </div>

              <div className="timeline-text">{entry.outcome}</div>

              {entry.justification && (
                <div
                  style={{
                    marginTop: "0.35rem",
                    fontSize: "0.85rem",
                    color: "var(--text-secondary)",
                    fontStyle: "italic",
                    borderLeft: "2px solid var(--accent-primary)",
                    paddingLeft: "0.5rem",
                    lineHeight: "1.4",
                  }}
                >
                  "{entry.justification}"
                </div>
              )}

              {observed.length > 0 && (
                <div
                  style={{
                    marginTop: "0.5rem",
                    fontSize: "0.75rem",
                    color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  Observed: {observed.join(" · ")}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
