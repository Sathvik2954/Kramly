import { useState } from "react";
import LearnerForm from "./components/LearnerForm";
import PathResult from "./components/PathResult";
import GraphVisualization from "./components/GraphVisualization";
import DecisionLogHistory from "./components/DecisionLogHistory";
import { fetchLearningPath } from "./api/client";

export default function App() {
  const [path, setPath] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentLearnerId, setCurrentLearnerId] = useState(null);

  async function handleSubmit({ learnerId, knownSkills, targetSkill }) {
    setLoading(true);
    setError(null);
    setCurrentLearnerId(learnerId);
    try {
      const result = await fetchLearningPath({ learnerId, knownSkills, targetSkill });
      setPath(result.ordered_path || result.path || []);
    } catch (e) {
      setError(e.message);
      setPath(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>
          Kramly <span className="badge">v0.1.0</span>
        </h1>
        <p className="app-description">
          An adaptive learning path optimizer powered by a knowledge dependency graph.
        </p>
      </header>

      <div className="dashboard-grid">
        <div className="dashboard-col">
          <section className="card">
            <h2>Optimize Path</h2>
            <LearnerForm onSubmit={handleSubmit} loading={loading} />
          </section>

          <section className="card">
            <h2>Learning Path</h2>
            <PathResult path={path} error={error} />
          </section>
        </div>

        <div className="dashboard-col">
          <section className="card" style={{ height: "100%" }}>
            <h2>Decision Audit Log</h2>
            <DecisionLogHistory learnerId={currentLearnerId} />
          </section>
        </div>
      </div>

      <section style={{ marginTop: "2.5rem" }}>
        <h2>Skill Dependency Network</h2>
        <div className="graph-container">
          <GraphVisualization />
        </div>
      </section>
    </div>
  );
}
