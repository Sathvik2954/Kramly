import { useState, useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import Nav from "./components/Nav";
import HomePage from "./pages/HomePage";
import LearningPathPage from "./pages/LearningPathPage";
import MarketplacePage from "./pages/MarketplacePage";
import AuditLogPage from "./pages/AuditLogPage";
import SkillGraphPage from "./pages/SkillGraphPage";
import { fetchLearningPath, fetchSkillGraph, fetchLearnerState } from "./api/client";

/**
 * App.jsx
 * Site shell: header, nav, and the route table. Learner/path state is
 * lifted here (not per-page) because it's shared across Learning Path,
 * Audit Log, and Marketplace pages — e.g. the audit log needs to know
 * which learner is currently active even though that learner was set on
 * a different page.
 */
export default function App() {
  const [path, setPath] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [currentLearnerId, setCurrentLearnerId] = useState("");
  const [decayedSkills, setDecayedSkills] = useState([]);

  // Full, all-domain skill list — lightweight metadata only (id/name/domain),
  // used for dropdown labels and name lookups across pages. NOT the same
  // thing as the Skill Graph page's visualization data, which is fetched
  // separately and scoped to one domain at a time.
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [graphError, setGraphError] = useState(null);
  const [graphLoading, setGraphLoading] = useState(true);

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
          Kramly <span className="version-badge">v0.1.0</span>
        </h1>
        <p className="app-description">
          Adaptive learning path optimizer. An LLM-driven agent computes the
          fastest route from what you know to what you want to learn.
        </p>
      </header>
      <div className="texture-strip" />
      <Nav />

      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route
          path="/learning-path"
          element={
            <LearningPathPage
              path={path}
              error={error}
              loading={loading}
              currentLearnerId={currentLearnerId}
              decayedSkills={decayedSkills}
              graphData={graphData}
              onSubmit={handleSubmit}
              onAction={handleActionTriggered}
            />
          }
        />
        <Route path="/marketplace" element={<MarketplacePage graphData={graphData} />} />
        <Route path="/audit-log" element={<AuditLogPage currentLearnerId={currentLearnerId} />} />
        <Route path="/skill-graph" element={<SkillGraphPage />} />
      </Routes>
    </div>
  );
}
