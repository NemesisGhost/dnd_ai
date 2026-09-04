import { NavLink } from 'react-router'

interface AppNavigationProps {
  campaignId: string
  askEnabled: boolean
  showAccess: boolean
}

const navigationItems = [
  { path: 'home', label: 'Home' },
  { path: 'world', label: 'World' },
  { path: 'characters', label: 'Characters' },
  { path: 'quests', label: 'Quests' },
  { path: 'sessions', label: 'Sessions' },
  { path: 'knowledge', label: 'Knowledge' },
]

export function AppNavigation({
  campaignId,
  askEnabled,
  showAccess,
}: AppNavigationProps) {
  const campaignPath = `/app/${campaignId}`

  return (
    <nav className="app-navigation" aria-label="Campaign">
      <ul className="app-navigation__list">
        <li>
          <NavLink
            className="app-navigation__link"
            to="/campaigns"
          >
            Change campaign
          </NavLink>
        </li>
        {navigationItems.map((item) => (
          <li key={item.path}>
            <NavLink
              className={({ isActive }) =>
                isActive
                  ? 'app-navigation__link app-navigation__link--active'
                  : 'app-navigation__link'
              }
              to={`${campaignPath}/${item.path}`}
            >
              {item.label}
            </NavLink>
          </li>
        ))}

        <li>
          {askEnabled ? (
            <NavLink
              className={({ isActive }) =>
                isActive
                  ? 'app-navigation__link app-navigation__link--active'
                  : 'app-navigation__link'
              }
              to={`${campaignPath}/ask`}
            >
              Ask
            </NavLink>
          ) : (
            <span
              className="app-navigation__link app-navigation__link--disabled"
              aria-disabled="true"
              title="Unavailable until Phase 12 is verified"
            >
              Ask
            </span>
          )}
        </li>

        {showAccess && (
          <li>
            <NavLink
              className={({ isActive }) =>
                isActive
                  ? 'app-navigation__link app-navigation__link--active'
                  : 'app-navigation__link'
              }
              to={`${campaignPath}/access`}
            >
              Access
            </NavLink>
          </li>
        )}
      </ul>
    </nav>
  )
}