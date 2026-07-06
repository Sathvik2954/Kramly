/**
 * PathResult.jsx
 * Displays the ordered learning path returned by the backend.
 *
 * ASSUMPTION FLAG: expects `path` to be an array of skill IDs (or objects
 * with an `id`/`name`) — actual shape not confirmed against your real
 * response.py model. Adjust the rendering below once confirmed.
 */
export default function PathResult({ path, error }) {
  if (error) {
    return (
      <div className="error-badge">
        <strong>Error:</strong> {error}
      </div>
    );
  }

  if (!path || path.length === 0) {
    return <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>No path computed yet. Submit the form above to generate a path.</p>;
  }

  return (
    <div>
      <h3 style={{ fontSize: "1rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Recommended Progression
      </h3>
      <ol className="step-list">
        {path.map((step, idx) => {
          const displayVal = typeof step === "string" ? step : step.name || step.id;
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
