import ForceGraph2D from "react-force-graph-2d";

/**
 * GraphVisualization.jsx
 *
 * Renders the full skill dependency graph using react-force-graph-2d.
 * Expects graphData: { nodes: [{id, name, domain}], links: [{source, target}] }
 * — this matches the shape returned by GET /graph in routes.py.
 */
export default function GraphVisualization({ graphData, error, loading }) {
  if (error) {
    return (
      <div className="graph-empty-state">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <h3>Database Unreachable</h3>
        <p style={{ maxWidth: "400px", margin: "0 auto 1rem auto" }}>
          Could not fetch the skill dependency network: {error}.
        </p>
        <div className="error-badge" style={{ display: "inline-block", maxWidth: "450px" }}>
          <strong>Troubleshooting:</strong> Make sure Neo4j is running locally, your <code>.env</code> credentials match, and you have run the seeder script.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="graph-empty-state">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="animate-spin">
          <line x1="12" y1="2" x2="12" y2="6" />
          <line x1="12" y1="18" x2="12" y2="22" />
          <line x1="4.93" y1="4.93" x2="7.76" y2="7.76" />
          <line x1="16.24" y1="16.24" x2="19.07" y2="19.07" />
          <line x1="2" y1="12" x2="6" y2="12" />
          <line x1="18" y1="12" x2="22" y2="12" />
          <line x1="4.93" y1="19.07" x2="7.76" y2="16.24" />
          <line x1="16.24" y1="7.76" x2="19.07" y2="4.93" />
        </svg>
        <h3>Loading Network Graph...</h3>
      </div>
    );
  }

  if (!graphData.nodes || graphData.nodes.length === 0) {
    return (
      <div className="graph-empty-state">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
        <h3>Empty Graph</h3>
        <p>No nodes or relationships were found in the database. Run the seeder to populate the graph.</p>
      </div>
    );
  }

  return (
    <div style={{ height: "500px", position: "relative" }}>
      <ForceGraph2D
        graphData={graphData}
        nodeLabel="name"
        backgroundColor="#FFFFFF"
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={1}
        linkColor={() => "#000000"}
        nodeColor={() => "#000000"}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.id;
          const fontSize = 12 / globalScale;
          ctx.font = `700 ${fontSize}px "JetBrains Mono", monospace`;
          const textWidth = ctx.measureText(label).width;
          const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.5); // padding

          ctx.fillStyle = "#FFFFFF";
          ctx.fillRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2, ...bckgDimensions);

          ctx.lineWidth = 1.5 / globalScale;
          ctx.strokeStyle = "#000000";
          ctx.strokeRect(node.x - bckgDimensions[0] / 2, node.y - bckgDimensions[1] / 2, ...bckgDimensions);

          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillStyle = "#000000";
          ctx.fillText(label, node.x, node.y);

          // Render node anchor point in Swiss Red
          ctx.beginPath();
          ctx.rect(node.x - 2, node.y - bckgDimensions[1] / 2 - 5, 4, 4);
          ctx.fillStyle = "#FF3000";
          ctx.fill();
        }}
      />
    </div>
  );
}
