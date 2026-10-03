import { NavLink } from "react-router"

// Persistent Home and Campaigns navigation, distinct from the per-campaign
// "Campaign" landmark rendered by AppNavigation (UI_DESIGN §4, §4.5).
export function GlobalNavigation() {
  return (
    <nav aria-label="Global" className="global-navigation">
      <ul className="global-navigation__list">
        <li>
          <NavLink to="/home" className="global-navigation__link">
            Home
          </NavLink>
        </li>
        <li>
          <NavLink to="/campaigns" className="global-navigation__link">
            Campaigns
          </NavLink>
        </li>
      </ul>
    </nav>
  )
}
