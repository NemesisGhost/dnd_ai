import {
  useEffect,
  useRef,
  useState
} from "react"
import { NavLink } from "react-router"
import type { LucideIcon } from "lucide-react"
import {
  BookOpen,
  CalendarDays,
  Globe2,
  House,
  Menu,
  MessageCircleQuestion,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ShieldCheck,
  Users,
  X,
} from "lucide-react"

interface NavigationItem {
  path: string
  label: string
  icon: LucideIcon
}

interface AppNavigationProps {
  campaignId: string
  askEnabled: boolean
  showAccess: boolean
}

const navigationItems: NavigationItem[] = [
  { path: 'home', label: 'Home', icon: House },
  { path: 'world', label: 'World', icon: Globe2 },
  { path: 'characters', label: 'Characters', icon: Users },
  { path: 'quests', label: 'Quests', icon: ScrollText },
  { path: 'sessions', label: 'Sessions', icon: CalendarDays },
  { path: 'knowledge', label: 'Knowledge', icon: BookOpen },
]

export function AppNavigation({
  campaignId,
  askEnabled,
  showAccess,
}: AppNavigationProps) {
  const campaignPath = `/app/${campaignId}`
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)

  const navigationClassName = [
    "app-navigation",
    collapsed
      ? "app-navigation--collapsed"
      : null,
    mobileOpen
      ? "app-navigation--mobile-open"
      : null,
  ]
    .filter(Boolean)
    .join(" ")

  function closeMobileNavigation(): void {
    setMobileOpen(false)
  }

  useEffect(() => {
    if (!mobileOpen) {
      return
    }

    function handleKeyDown(
      event: KeyboardEvent,
    ): void {
      if (event.key !== "Escape") {
        return
      }

      setMobileOpen(false)
      mobileToggleRef.current?.focus()
    }

    document.addEventListener(
      "keydown",
      handleKeyDown,
    )

    return () => {
      document.removeEventListener(
        "keydown",
        handleKeyDown,
      )
    }
  }, [mobileOpen])

  return (
    <>
      <button
        ref={mobileToggleRef}
        type="button"
        className="app-navigation__mobile-toggle"
        aria-controls="campaign-navigation-list"
        aria-expanded={mobileOpen}
        aria-label={
          mobileOpen
            ? "Close campaign navigation"
            : "Open campaign navigation"
        }
        onClick={() =>
          setMobileOpen(
            (currentValue) => !currentValue,
          )
        }
      >
        {mobileOpen ? (
          <X aria-hidden="true" />
        ) : (
          <Menu aria-hidden="true" />
        )}

        <span>
          {mobileOpen ? "Close" : "Menu"}
        </span>
      </button>
      {mobileOpen && (
        <button
          type="button"
          className="app-navigation__backdrop"
          aria-label="Dismiss campaign navigation"
          onClick={closeMobileNavigation}
        />
      )}
      <nav className={navigationClassName} aria-label="Campaign">
        <ul id="campaign-navigation-list" className="app-navigation__list">
          {navigationItems.map((item) => {
            const Icon = item.icon
            return (
              <li key={item.path}>
                <NavLink
                  className={({ isActive }) =>
                    isActive
                      ? 'app-navigation__link app-navigation__link--active'
                      : 'app-navigation__link'
                  }
                  to={`${campaignPath}/${item.path}`}
                  title={collapsed ? item.label : undefined}
                  onClick={closeMobileNavigation}
                >
                  <Icon className="app-navigation__icon" aria-hidden="true" />
                  <span className="app-navigation__label">{item.label}</span>
                </NavLink>
              </li>
            )
          })}

          <li>
            {askEnabled ? (
              <NavLink
                className={({ isActive }) =>
                  isActive
                    ? "app-navigation__link app-navigation__link--active"
                    : "app-navigation__link"
                }
                to={`${campaignPath}/ask`}
                title={collapsed ? "Ask" : undefined}
                onClick={closeMobileNavigation}
              >
                <MessageCircleQuestion
                  className="app-navigation__icon"
                  aria-hidden="true"
                />

                <span className="app-navigation__label">
                  Ask
                </span>
              </NavLink>
            ) : (
              <span
                className="app-navigation__link app-navigation__link--disabled"
                aria-disabled="true"
                title="Unavailable until Phase 12 is verified"
              >
                <MessageCircleQuestion
                  className="app-navigation__icon"
                  aria-hidden="true"
                />

                <span className="app-navigation__label">
                  Ask
                </span>
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
                onClick={closeMobileNavigation}
              >
                <ShieldCheck className="app-navigation__icon" aria-hidden="true" />
                <span className="app-navigation__label">
                  Access
                </span>
              </NavLink>
            </li>
          )}

          <li className="app-navigation__toggle-item">
            <button
              type="button"
              className="app-navigation__toggle"
              aria-controls="campaign-navigation-list"
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
              onClick={() => setCollapsed((currentValue) => !currentValue)}
            >
              {collapsed ? (
                <PanelLeftOpen
                  className="app-navigation__icon"
                  aria-hidden="true"
                />
              ) : (
                <PanelLeftClose
                  className="app-navigation__icon"
                  aria-hidden="true"
                />
              )}

              <span className="app-navigation__label">
                {collapsed
                  ? "Expand navigation"
                  : "Collapse navigation"}
              </span>
            </button>
          </li>

        </ul>
      </nav>
    </>
  )
}