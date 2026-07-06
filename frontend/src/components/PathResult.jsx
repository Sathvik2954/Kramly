/**
 * PathResult.jsx
 * Displays the ordered learning path returned by the backend.
 *
 * ASSUMPTION FLAG: expects `path` to be an array of skill IDs (or objects
 * with an `id`/`name`) — actual shape not confirmed against your real
 * response.py model. Adjust the rendering below once confirmed.
 */
export default function PathResult({ path, error, graphData }) {
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

  // Map IDs to descriptive names from graph data
  const nameMap = {};
  if (graphData && graphData.nodes) {
    graphData.nodes.forEach((node) => {
      nameMap[node.id] = node.name;
    });
  }

  return (
    <div>
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
