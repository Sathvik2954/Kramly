import MarketplacePanel from "../components/MarketplacePanel";

/**
 * MarketplacePage.jsx
 * Standalone page for the study notes marketplace. graphData here is the
 * lightweight all-domain skill list from App.jsx (used for the skill
 * picker dropdowns), not the Skill Graph page's visualization data.
 */
export default function MarketplacePage({ graphData }) {
  return (
    <section className="card">
      <div className="card-label">
        <span className="card-index">01</span>
        <span>Study Notes Marketplace</span>
      </div>
      <div className="card-body">
        <MarketplacePanel graphData={graphData} />
      </div>
    </section>
  );
}
