import { useEffect, useId, useRef, useState } from "react"
import type {
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from "react"
import { Link, NavLink, useLocation } from "react-router"
import { ChevronDown } from "lucide-react"
import type { LucideIcon } from "lucide-react"

export interface ExpandableNavItem {
  to: string
  label: string
  // Exact-path match (NavLink's `end`).
  end?: boolean
  // Overrides the route match, for a child whose section excludes a sibling's
  // sub-routes (Knowledge "Claims" must not stay active under Member preview).
  isActive?: (pathname: string) => boolean
}

interface ExpandableNavGroupProps {
  icon: LucideIcon
  label: string
  // Whether the current route lies anywhere in this group.
  sectionActive: boolean
  items: ExpandableNavItem[]
  collapsed: boolean
  onNavigate: () => void
}

// A parent disclosure over child links (mirrors ProfileMenu's button +
// aria-expanded + aria-controls pattern, adapted for an inline item nested in
// the vertical sidebar rather than a floating popup). Shared by the Access and
// Knowledge groups.
export function ExpandableNavGroup({
  icon: Icon,
  label,
  sectionActive: isAccessSectionActive,
  items,
  collapsed,
  onNavigate,
}: ExpandableNavGroupProps) {
  const location = useLocation()
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
  // Focus moves into the submenu only when the user opens it, never when
  // it starts open for the active route — otherwise every remount of the
  // persistent sidebar (a campaign-scope change) would steal focus.
  const focusOnOpenRef = useRef(false)
  const submenuId = useId()

  useEffect(() => {
    if (open && focusOnOpenRef.current) {
      focusOnOpenRef.current = false
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
      // Handled here, not globally, so it cannot fight the sidebar's own
      // document-level Escape handler for the mobile drawer.
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

  function subLinkClassName({ isActive }: { isActive: boolean }): string {
    return isActive
      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
      : "portal-sidebar__sublink"
  }

  return (
    <li
      ref={containerRef}
      className="portal-sidebar__access-group"
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
    >
      <button
        ref={buttonRef}
        type="button"
        className={
          isAccessSectionActive
            ? "portal-sidebar__link portal-sidebar__link--active"
            : "portal-sidebar__link"
        }
        aria-expanded={open}
        aria-controls={submenuId}
        title={collapsed ? label : undefined}
        onClick={() => {
          if (!open) {
            focusOnOpenRef.current = true
          }
          setOpen((current) => !current)
        }}
      >
        <Icon className="portal-sidebar__icon" aria-hidden="true" />
        <span className="portal-sidebar__label">{label}</span>
        <ChevronDown
          className={
            open
              ? "portal-sidebar__chevron portal-sidebar__chevron--open"
              : "portal-sidebar__chevron"
          }
          aria-hidden="true"
        />
      </button>

      <ul id={submenuId} className="portal-sidebar__submenu" hidden={!open}>
        {items.map((item, index) => {
          const active = item.isActive?.(location.pathname)
          return (
            <li key={item.to}>
              {active !== undefined ? (
                <Link
                  ref={index === 0 ? firstItemRef : undefined}
                  className={
                    active
                      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
                      : "portal-sidebar__sublink"
                  }
                  aria-current={active ? "page" : undefined}
                  to={item.to}
                  onClick={handleChildActivated}
                >
                  <span className="portal-sidebar__label">{item.label}</span>
                </Link>
              ) : (
                <NavLink
                  ref={index === 0 ? firstItemRef : undefined}
                  end={item.end}
                  className={subLinkClassName}
                  to={item.to}
                  onClick={handleChildActivated}
                >
                  <span className="portal-sidebar__label">{item.label}</span>
                </NavLink>
              )}
            </li>
          )
        })}
      </ul>
    </li>
  )
}
