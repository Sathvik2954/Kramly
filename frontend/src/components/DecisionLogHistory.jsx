import { useEffect, useState } from "react";
import { fetchDecisionLogHistory } from "../api/client";

/**
 * DecisionLogHistory.jsx
 * Shows past re-planning decisions: what changed and why (Phase 2.4,
 * Person B's logging work).
 *
 * NOTE: the /decision-log/{learnerId} endpoint does not exist in your
 * backend yet per project_structure.md. This component will show the
 * error state until Person B adds it.
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
        {entries.map((entry, idx) => (
          <li key={idx} className="timeline-item">
            <span className="timeline-marker"></span>
            <span className="timeline-time">
              {entry.timestamp}
              <span className="timeline-trigger">{entry.trigger}</span>
            </span>
            <div className="timeline-text">{entry.summary}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
