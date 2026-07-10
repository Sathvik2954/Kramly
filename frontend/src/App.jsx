import { useState, useEffect } from "react";
import LearnerForm from "./components/LearnerForm";
import PathResult from "./components/PathResult";
import GraphVisualization from "./components/GraphVisualization";
import DecisionLogHistory from "./components/DecisionLogHistory";
import LearnerConfigForm from "./components/LearnerConfigForm";
import MarketplacePanel from "./components/MarketplacePanel";
import { fetchLearningPath, fetchSkillGraph, fetchLearnerState } from "./api/client";

export default function App() {
  const [path, setPath] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentLearnerId, setCurrentLearnerId] = useState("");
  const [decayedSkills, setDecayedSkills] = useState([]);

  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [graphError, setGraphError] = useState(null);
  const [graphLoading, setGraphLoading] = useState(true);

  // Load graph on mount
  useEffect(() => {
    loadGraph();
  }, []);

  async function loadGraph() {
    setGraphLoading(true);
    setGraphError(null);
    try {
      const data = await fetchSkillGraph();
      setGraphData(data);
    } catch (e) {
      setGraphError(e.message);
    } finally {
      setGraphLoading(false);
    }
  }

  // Reload learner path & log histories
  async function handleActionTriggered() {
    if (!currentLearnerId) return;
    setLoading(true);
    setError(null);
    try {
      const state = await fetchLearnerState(currentLearnerId);
      if (state) {
        setDecayedSkills(state.decayed_skills || []);
        if (state.target_skill) {
          const result = await fetchLearningPath({
            learnerId: currentLearnerId,
            knownSkills: state.known_skills || [],
            targetSkill: state.target_skill,
          });
          setPath(result.path || []);
        } else {
          setPath(null);
        }
      } else {
        setDecayedSkills([]);
        setPath(null);
      }
    } catch (e) {
      setError(e.message);
      setPath(null);
      setDecayedSkills([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit({ learnerId, knownSkills, targetSkill }) {
    setLoading(true);
    setError(null);
    setCurrentLearnerId(learnerId);
    try {
      const result = await fetchLearningPath({ learnerId, knownSkills, targetSkill });
      setPath(result.path || []);
      
      const state = await fetchLearnerState(learnerId);
      if (state) {
        setDecayedSkills(state.decayed_skills || []);
      } else {
        setDecayedSkills([]);
      }
    } catch (e) {
      setError(e.message);
      setPath(null);
      setDecayedSkills([]);
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
            <PathResult path={path} error={error} graphData={graphData} decayedSkills={decayedSkills} />
          </section>

          <section className="card">
            <h2>Study Notes Marketplace</h2>
            <MarketplacePanel graphData={graphData} />
          </section>
        </div>

        <div className="dashboard-col">
          <section className="card">
            <h2>Evidence & Target Config</h2>
            <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "-0.5rem", marginBottom: "1rem" }}>
              {currentLearnerId 
                ? `Recording updates for active learner: "${currentLearnerId}"`
                : "Generate a path first to unlock target and evidence submissions."}
            </p>
            <LearnerConfigForm 
              learnerId={currentLearnerId} 
              onAction={handleActionTriggered} 
              loading={loading} 
            />
          </section>

          <section className="card">
            <h2>Decision Audit Log</h2>
            <DecisionLogHistory learnerId={currentLearnerId} />
          </section>
        </div>
      </div>

      <section style={{ marginTop: "2.5rem" }}>
        <h2>Skill Dependency Network</h2>
        <div className="graph-container">
          <GraphVisualization graphData={graphData} error={graphError} loading={graphLoading} />
        </div>
      </section>
    </div>
  );
}
