import { useState } from "react";

/**
 * LearnerForm.jsx
 * Collects learner ID, known skills (comma-separated for simplicity),
 * and target skill, then submits to fetch a learning path.
 */
export default function LearnerForm({ onSubmit, loading }) {
  const [learnerId, setLearnerId] = useState("");
  const [knownSkillsInput, setKnownSkillsInput] = useState("");
  const [targetSkill, setTargetSkill] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    const knownSkills = knownSkillsInput
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    onSubmit({ learnerId, knownSkills, targetSkill });
  }

  return (
    <form onSubmit={handleSubmit} className="form-container">
      <div className="input-group">
        <label>
          Learner ID
          <input
            type="text"
            value={learnerId}
            onChange={(e) => setLearnerId(e.target.value)}
            placeholder="e.g. learner_001"
            required
          />
        </label>
      </div>

      <div className="input-group">
        <label>
          Known Skills (comma-separated skill IDs)
          <input
            type="text"
            value={knownSkillsInput}
            onChange={(e) => setKnownSkillsInput(e.target.value)}
            placeholder="e.g. C001, C002, WEB001"
          />
        </label>
      </div>

      <div className="input-group">
        <label>
          Target Skill (skill ID)
          <input
            type="text"
            value={targetSkill}
            onChange={(e) => setTargetSkill(e.target.value)}
            placeholder="e.g. WEB010"
            required
          />
        </label>
      </div>

      <button type="submit" disabled={loading}>
        {loading ? "Computing path..." : "Get Learning Path"}
      </button>
    </form>
  );
}
