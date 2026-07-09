import { useEffect, useState } from "react";
import { fetchDecisionLogHistory } from "../api/client";

/**
 * DecisionLogHistory.jsx
 * Shows past re-planning decisions: what changed and why.
 * Calls GET /decision-log/{learnerId} — returns DecisionLogEntry[] from the
 * in-memory DECISION_LOGS store in routes.py.
 */
export default function DecisionLogHistory({ learnerId }) {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!learnerId) return;
    setLoading(true);
    setError(null);
    fetchDecisionLogHistory(learnerId)
      .then((data) => setEntries(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [learnerId]);

  if (!learnerId) {
    return <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>Enter a learner ID to view decision history.</p>;
  }

  if (loading) return <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>Loading history...</p>;

  if (error) {
    return (
      <div className="error-badge">
        <strong>Error:</strong> Could not load decision log: {error}
      </div>
    );
  }

  if (entries.length === 0) {
    return <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>No re-planning decisions logged yet for this learner.</p>;
  }

  return (
    <div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
        Audit Trail for "{learnerId}"
      </h3>
      <ul className="timeline">
        {entries.map((entry, idx) => {
          const trigger = entry.event_type || entry.trigger || "Unknown";
          const summary = entry.reason || entry.summary || "";
          
          // Format ISO timestamp or fallback to raw string
          let formattedTime = entry.timestamp;
          try {
            if (entry.timestamp.includes("T")) {
              formattedTime = new Date(entry.timestamp).toLocaleString();
            }
          } catch (e) {
            // use fallback
          }

          const hasDeltas = (entry.added_skills && entry.added_skills.length > 0) || 
                            (entry.removed_skills && entry.removed_skills.length > 0);

          return (
            <li key={idx} className="timeline-item">
              <span className="timeline-marker"></span>
              <span className="timeline-time">
                {formattedTime}
                <span className="timeline-trigger">{trigger}</span>
              </span>
              <div className="timeline-text">{summary}</div>
              {entry.natural_language_explanation && (
                <div style={{
                  marginTop: "0.35rem",
                  fontSize: "0.85rem",
                  color: "var(--text-secondary)",
                  fontStyle: "italic",
                  borderLeft: "2px solid var(--accent-primary)",
                  paddingLeft: "0.5rem",
                  lineHeight: "1.4"
                }}>
                  "{entry.natural_language_explanation}"
                </div>
              )}
              
              {hasDeltas && (
                <div style={{ 
                  marginTop: "0.5rem", 
                  fontSize: "0.8rem", 
                  color: "var(--text-muted)", 
                  display: "flex", 
                  flexDirection: "column",
                  gap: "0.25rem" 
                }}>
                  {entry.added_skills && entry.added_skills.length > 0 && (
                    <div>
                      <span style={{ color: "var(--accent-success)", fontWeight: 500 }}>+ Added:</span>{" "}
                      <code style={{ fontFamily: "var(--font-mono)" }}>{entry.added_skills.join(", ")}</code>
                    </div>
                  )}
                  {entry.removed_skills && entry.removed_skills.length > 0 && (
                    <div>
                      <span style={{ color: "var(--accent-error)", fontWeight: 500 }}>- Removed:</span>{" "}
                      <code style={{ fontFamily: "var(--font-mono)" }}>{entry.removed_skills.join(", ")}</code>
                    </div>
                  )}
                </div>
              )}

              {entry.execution_time_ms !== undefined && (
                <div style={{ marginTop: "0.25rem", fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  Resolved in {Number(entry.execution_time_ms).toFixed(1)}ms
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
