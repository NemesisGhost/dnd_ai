import {
  useEffect,
  useId,
  useRef,
  useState
} from "react"
import type {
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from "react"
import { NavLink, useLocation } from "react-router"
import type { LucideIcon } from "lucide-react"
import {
  BookOpen,
  CalendarDays,
  ChevronDown,
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
  { path: 'home', label: 'Campaign Home', icon: House },
  { path: 'world', label: 'World', icon: Globe2 },
  { path: 'characters', label: 'Characters', icon: Users },
  { path: 'quests', label: 'Quests', icon: ScrollText },
  { path: 'sessions', label: 'Sessions', icon: CalendarDays },
  { path: 'knowledge', label: 'Knowledge', icon: BookOpen },
]

interface AccessNavGroupProps {
  campaignPath: string
  collapsed: boolean
  onNavigate: () => void
}

// Access as a parent disclosure over "Access Management" and
// "Invitations" (navigation plan: mirrors ProfileMenu's button +
// aria-expanded + aria-controls pattern, adapted for an inline item
// nested in this vertical rail rather than a floating popup). Both
// children share the same `access.manage` gate, so the whole group is
// shown or hidden by the caller's `showAccess` the same way the flat
// link used to be.
function AccessNavGroup({
  campaignPath,
  collapsed,
  onNavigate,
}: AccessNavGroupProps) {
  const location = useLocation()
  const accessBasePath = `${campaignPath}/access`
  const isAccessSectionActive =
    location.pathname === accessBasePath ||
    location.pathname.startsWith(`${accessBasePath}/`)

  // Computed once, lazily, from whichever route is active on mount: a
  // direct load/refresh of a child route starts with the submenu
  // already open. It deliberately does not react to later navigation,
  // so choosing a child destination through this menu still closes it
  // (closeAndFocusButton / handleChildActivated below) instead of being
  // immediately reopened by the route becoming active underneath it.
  const [open, setOpen] = useState(() => isAccessSectionActive)
  const containerRef = useRef<HTMLLIElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const firstItemRef = useRef<HTMLAnchorElement>(null)
  const submenuId = useId()

  useEffect(() => {
    if (open) {
      firstItemRef.current?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return
    }

    function handlePointerDown(event: PointerEvent): void {
      const target = event.target as Node | null

      if (target !== null && containerRef.current?.contains(target)) {
        return
      }

      // Outside dismissal never moves focus, so an outside control the
      // user activated keeps it.
      setOpen(false)
    }

    document.addEventListener("pointerdown", handlePointerDown)

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
    }
  }, [open])

  function closeAndFocusButton(): void {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLLIElement>): void {
    if (event.key === "Escape" && open) {
      // Handled here, not globally, so it cannot fight this component's
      // own document-level Escape handler for the mobile drawer.
      event.stopPropagation()
      closeAndFocusButton()
    }
  }

  function handleBlur(event: ReactFocusEvent<HTMLLIElement>): void {
    if (!open) {
      return
    }

    const next = event.relatedTarget as Node | null

    if (next !== null && containerRef.current?.contains(next)) {
      return
    }

    setOpen(false)
  }

  function handleChildActivated(): void {
    setOpen(false)
    onNavigate()
  }

  return (
    <li
      ref={containerRef}
      className="app-navigation__access-group"
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
    >
      <button
        ref={buttonRef}
        type="button"
        className={
          isAccessSectionActive
            ? "app-navigation__link app-navigation__link--active"
            : "app-navigation__link"
        }
        aria-expanded={open}
        aria-controls={submenuId}
        title={collapsed ? "Access" : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        <ShieldCheck className="app-navigation__icon" aria-hidden="true" />
        <span className="app-navigation__label">Access</span>
        <ChevronDown
          className={
            open
              ? "app-navigation__chevron app-navigation__chevron--open"
              : "app-navigation__chevron"
          }
          aria-hidden="true"
        />
      </button>

      <ul
        id={submenuId}
        className="app-navigation__submenu"
        hidden={!open}
      >
        <li>
          <NavLink
            ref={firstItemRef}
            end
            className={({ isActive }) =>
              isActive
                ? "app-navigation__sublink app-navigation__sublink--active"
                : "app-navigation__sublink"
            }
            to={accessBasePath}
            onClick={handleChildActivated}
          >
            <span className="app-navigation__label">Access Management</span>
          </NavLink>
        </li>
        <li>
          <NavLink
            className={({ isActive }) =>
              isActive
                ? "app-navigation__sublink app-navigation__sublink--active"
                : "app-navigation__sublink"
            }
            to={`${accessBasePath}/invitations`}
            onClick={handleChildActivated}
          >
            <span className="app-navigation__label">Invitations</span>
          </NavLink>
        </li>
      </ul>
    </li>
  )
}

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
          {mobileOpen ? "Close" : "Campaign menu"}
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
            <AccessNavGroup
              campaignPath={campaignPath}
              collapsed={collapsed}
              onNavigate={closeMobileNavigation}
            />
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