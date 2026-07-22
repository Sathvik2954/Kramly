import { Link } from "react-router-dom";

const TILES = [
  {
    index: "01",
    title: "Learning Path",
    description: "Submit known skills and a target to get an ordered, agent-computed learning path. Record quiz evidence and set targets here too.",
    to: "/learning-path",
  },
  {
    index: "02",
    title: "Marketplace",
    description: "Search and rate community study notes, or contribute your own — resources are matched to skills automatically.",
    to: "/marketplace",
  },
  {
    index: "03",
    title: "Audit Log",
    description: "See every re-planning decision the agent has made for the active learner, and why it made it.",
    to: "/audit-log",
  },
  {
    index: "04",
    title: "Skill Graph",
    description: "Explore the prerequisite dependency network for a single domain at a time.",
    to: "/skill-graph",
  },
];

/**
 * HomePage.jsx
 * Landing page. No shared app state needed here — just orientation and
 * navigation into the four feature pages.
 */
export default function HomePage() {
  return (
    <div>
      <section className="card">
        <div className="card-label">
          <span className="card-index">00</span>
          <span>Welcome</span>
        </div>
        <div className="card-body">
          <p style={{ fontSize: "0.95rem", color: "var(--text-secondary)", maxWidth: "60ch", margin: 0 }}>
            Kramly models a domain's skills as a dependency graph and uses an
            LLM-driven agent to compute the shortest valid path from what you
            already know to what you want to learn — then keeps that path
            current as your evidence changes. Pick a section below to get started.
          </p>
        </div>
      </section>

      <div className="home-tile-grid">
        {TILES.map((tile) => (
          <Link key={tile.to} to={tile.to} className="home-tile">
            <div className="card-label">
              <span className="card-index">{tile.index}</span>
              <span>{tile.title}</span>
            </div>
            <div className="card-body">
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: 0 }}>
                {tile.description}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
