/**
 * PathResult.jsx
 * Displays the ordered learning path returned by the backend.
 *
 * Response shape (confirmed against models/response.py):
 *   { path: string[] }  — ordered list of skill IDs, empty if already known.
 */
export default function PathResult({ path, error, graphData, decayedSkills = [] }) {
  // Map IDs to descriptive names from graph data
  const nameMap = {};
  if (graphData && graphData.nodes) {
    graphData.nodes.forEach((node) => {
      nameMap[node.id] = node.name;
    });
  }

  if (error) {
    let errTitle = "Error";
    let errDetail = error;
    
    // Distinguish specific error categories for the audit checklist
    if (error.includes("Failed to fetch") || error.includes("NetworkError")) {
      errTitle = "Connection Failure";
      errDetail = "Could not reach the server API. Verify that the FastAPI backend is running locally.";
    } else if (error.toLowerCase().includes("cycle")) {
      errTitle = "Dependency Cycle Conflict";
    } else if (error.toLowerCase().includes("not found")) {
      errTitle = "Invalid Concept ID";
    }

    return (
      <div className="error-badge">
        <strong>{errTitle}:</strong> {errDetail}
      </div>
    );
  }

  if (path === null) {
    return <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>No path computed yet. Submit the form above to generate a path.</p>;
  }

  if (path.length === 0) {
    return (
      <div style={{ 
        padding: "1rem", 
        backgroundColor: "var(--accent-success-bg)", 
        border: "1px solid var(--accent-success)", 
        borderRadius: "8px", 
        fontSize: "0.9rem", 
        color: "var(--text-primary)" 
      }}>
        <strong>Already Mastered:</strong> You already know the target skill! No additional training required.
      </div>
    );
  }

  return (
    <div>
      {decayedSkills && decayedSkills.length > 0 && (
        <div style={{
          padding: "0.75rem 1rem",
          backgroundColor: "var(--accent-error-bg)",
          border: "1px solid var(--accent-error)",
          borderRadius: "8px",
          fontSize: "0.85rem",
          color: "var(--text-primary)",
          marginBottom: "1rem"
        }}>
          <strong style={{ display: "block", marginBottom: "0.25rem" }}>⚠️ Forgotten concepts detected:</strong>
          <ul style={{ margin: "0", paddingLeft: "1.25rem", color: "var(--text-secondary)" }}>
            {decayedSkills.map(id => (
              <li key={id}>
                <code style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{id}</code>
                {nameMap[id] ? ` — ${nameMap[id]}` : ""}
              </li>
            ))}
          </ul>
          <p style={{ margin: "0.5rem 0 0 0", fontSize: "0.75rem", color: "var(--text-muted)" }}>
            These concepts have decayed below the threshold and have been automatically added back to your active learning path.
          </p>
        </div>
      )}

      <h3 style={{ fontSize: "1rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Recommended Progression
      </h3>
      <ol className="step-list">
        {path.map((step, idx) => {
          const stepId = typeof step === "string" ? step : step.id;
          const name = nameMap[stepId] || (typeof step !== "string" ? step.name : null);
          const displayVal = name ? `${name} (${stepId})` : stepId;
          return (
            <li key={idx} className="step-item">
              <span className="step-number">{idx + 1}</span>
              <span className="step-content">{displayVal}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
