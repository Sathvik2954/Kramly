import { useState, useEffect } from "react";
import GraphVisualization from "../components/GraphVisualization";
import { fetchDomains, fetchSkillGraph } from "../api/client";

/**
 * SkillGraphPage.jsx
 * Domain-scoped skill dependency network. Starts empty on purpose — no
 * graph is fetched or rendered until a domain is picked, and picking a
 * different domain re-fetches instead of accumulating onto what's already
 * drawn. Previously the graph endpoint had no domain filter at all, so
 * every domain's skills rendered together in one blob; this page (plus
 * the domain param added to GET /graph) fixes that.
 */
export default function SkillGraphPage() {
  const [domains, setDomains] = useState([]);
  const [domainsError, setDomainsError] = useState(null);
  const [selectedDomain, setSelectedDomain] = useState("");

  const [graphData, setGraphData] = useState(null);
  const [graphError, setGraphError] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => {
    fetchDomains()
      .then(setDomains)
      .catch((e) => setDomainsError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedDomain) {
      // No domain chosen (yet, or reset back to the placeholder option) —
      // clear any previously-rendered graph instead of leaving stale data.
      setGraphData(null);
      setGraphError(null);
      return;
    }

    let cancelled = false;
    setGraphLoading(true);
    setGraphError(null);

    fetchSkillGraph(selectedDomain)
      .then((data) => {
        if (!cancelled) setGraphData(data);
      })
      .catch((e) => {
        if (!cancelled) setGraphError(e.message);
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedDomain]);

  return (
    <section className="card">
      <div className="card-label">
        <span className="card-index">01</span>
        <span>Skill Dependency Network</span>
      </div>
      <div className="card-body">
        <div className="input-group" style={{ maxWidth: "320px", marginBottom: "1.25rem" }}>
          <label htmlFor="skill-graph-domain-select">Domain</label>
          <select
            id="skill-graph-domain-select"
            value={selectedDomain}
            onChange={(e) => setSelectedDomain(e.target.value)}
          >
            <option value="">-- Choose a domain --</option>
            {domains.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>

        {domainsError && (
          <div className="error-badge" style={{ marginBottom: "1rem" }}>
            <strong>Error:</strong> Could not load domain list: {domainsError}
          </div>
        )}

        {!selectedDomain ? (
          <div className="graph-empty-state">
            <h3>No domain selected</h3>
            <p>Choose a domain above to load its skill dependency network.</p>
          </div>
        ) : (
          <div className="graph-container">
            <GraphVisualization graphData={graphData || { nodes: [], links: [] }} error={graphError} loading={graphLoading} />
          </div>
        )}
      </div>
    </section>
  );
}
