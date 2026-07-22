import LearnerForm from "../components/LearnerForm";
import PathResult from "../components/PathResult";
import LearnerConfigForm from "../components/LearnerConfigForm";

/**
 * LearningPathPage.jsx
 * The core learner workflow: submit known skills + target, see the
 * computed path, and manage evidence/target updates for the active
 * learner. All state is owned by App.jsx and passed down as props since
 * it's shared with the Audit Log page too.
 */
export default function LearningPathPage({
  path,
  error,
  loading,
  currentLearnerId,
  decayedSkills,
  graphData,
  onSubmit,
  onAction,
}) {
  return (
    <div className="dashboard-grid">
      <div className="dashboard-col">
        <section className="card">
          <div className="card-label">
            <span className="card-index">01</span>
            <span>Optimize Path</span>
          </div>
          <div className="card-body">
            <LearnerForm onSubmit={onSubmit} loading={loading} />
          </div>
        </section>

        <section className="card">
          <div className="card-label">
            <span className="card-index">02</span>
            <span>Learning Path</span>
          </div>
          <div className="card-body">
            <PathResult path={path} error={error} graphData={graphData} decayedSkills={decayedSkills} />
          </div>
        </section>
      </div>

      <div className="dashboard-col">
        <section className="card">
          <div className="card-label">
            <span className="card-index">03</span>
            <span>Evidence &amp; Target Config</span>
          </div>
          <div className="card-body">
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 0, marginBottom: "1rem", fontFamily: "var(--font-mono)" }}>
              {currentLearnerId
                ? `Recording updates for active learner: "${currentLearnerId}"`
                : "Generate a path first to unlock target and evidence submissions."}
            </p>
            <LearnerConfigForm
              learnerId={currentLearnerId}
              onAction={onAction}
              loading={loading}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
