import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { index: "01", label: "Home", to: "/" },
  { index: "02", label: "Learning Path", to: "/learning-path" },
  { index: "03", label: "Marketplace", to: "/marketplace" },
  { index: "04", label: "Audit Log", to: "/audit-log" },
  { index: "05", label: "Skill Graph", to: "/skill-graph" },
];

/**
 * Nav.jsx
 * Top-level site navigation between the 5 pages. Swiss-style: uppercase,
 * numbered entries, active route gets a solid red underline.
 */
export default function Nav() {
  return (
    <nav className="site-nav">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          className={({ isActive }) => "site-nav-link" + (isActive ? " site-nav-link-active" : "")}
        >
          <span className="site-nav-index">{item.index}</span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
