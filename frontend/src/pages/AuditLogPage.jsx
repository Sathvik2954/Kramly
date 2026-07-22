import DecisionLogHistory from "../components/DecisionLogHistory";
import AgenticDecisionLog from "../components/AgenticDecisionLog";

/**
 * AuditLogPage.jsx
 * Standalone page for the agent's audit trail for the currently active
 * learner (set on the Learning Path page). Two sections: the original
 * decision log (every recompute of the path, whoever/whatever triggered
 * it) and the newer agentic reasoning trace (what the observe-reason-act
 * loop chose from its full action space and why) - kept as separate
 * cards rather than merged, since they're backed by different Neo4j node
 * types and different trigger populations (manual/API replans vs the
 * autonomous scheduler's decay-triggered cycles).
 */
export default function AuditLogPage({ currentLearnerId }) {
  return (
    <>
      <section className="card">
        <div className="card-label">
          <span className="card-index">01</span>
          <span>Decision Audit Log</span>
        </div>
        <div className="card-body">
          <DecisionLogHistory learnerId={currentLearnerId} />
        </div>
      </section>

      <section className="card" style={{ marginTop: "1.5rem" }}>
        <div className="card-label">
          <span className="card-index">02</span>
          <span>Agentic Reasoning Trace</span>
        </div>
        <div className="card-body">
          <AgenticDecisionLog learnerId={currentLearnerId} />
        </div>
      </section>
    </>
  );
}
