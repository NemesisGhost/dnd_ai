import { useId } from "react"
import { Link, NavLink, useLocation } from "react-router"
import { ChevronDown } from "lucide-react"
import { DisabledNavItem } from "./DisabledNavItem"
import type { LucideIcon } from "lucide-react"
import { navTaskState } from "../navigation/navStart"
import type { NavRoot } from "../navigation/routeMeta"
import { MENU_CONTROL_ATTRIBUTE, useSidebarMenu } from "./useSidebarMenu"

export interface ExpandableNavItem {
  to: string
  label: string
  // Exact-path match (NavLink's `end`).
  end?: boolean
  // Overrides the route match, for a child whose section excludes a sibling's
  // sub-routes (Knowledge "Claims" must not stay active under Member preview).
  isActive?: (pathname: string) => boolean
  // When set, the child is shown as the disabled-navigation entry with this neutral
  // reason instead of a link (see DisabledNavItem).
  unavailableReason?: string
  // The task root this child starts, when it differs from the group's (Campaign Settings in Access).
  root?: NavRoot
}

interface ExpandableNavGroupProps {
  icon: LucideIcon
  label: string
  // Whether the current route lies anywhere in this group.
  sectionActive: boolean
  // The task root every child starts (docs/UI_DESIGN.md §4.8); a child may override it.
  root: NavRoot
  items: ExpandableNavItem[]
  collapsed: boolean
  onNavigate: () => void
}

// A parent disclosure over child links (mirrors ProfileMenu's button +
// aria-expanded + aria-controls pattern, adapted for an inline item nested in
// the vertical sidebar rather than a floating popup). Shared by the Access,
// Knowledge and Items groups. Open, close and focus follow `useSidebarMenu`.
export function ExpandableNavGroup({
  icon: Icon,
  root,
  label,
  sectionActive: isAccessSectionActive,
  items,
  collapsed,
  onNavigate,
}: ExpandableNavGroupProps) {
  const location = useLocation()
  // Computed once, from whichever route is active on mount: a direct load/refresh of a child route
  // starts with the submenu already open (and never takes focus). It deliberately does not react to
  // later navigation, so choosing a child through this menu closes it on acceptance instead of being
  // immediately reopened by the route becoming active underneath it.
  const { menu, containerRef, submenuRef } = useSidebarMenu({
    initialOpen: isAccessSectionActive,
    onNavigate,
  })
  const { open } = menu
  const submenuId = useId()

  function subLinkClassName({ isActive }: { isActive: boolean }): string {
    return isActive
      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
      : "portal-sidebar__sublink"
  }

  return (
    <li
      ref={containerRef}
      className="portal-sidebar__access-group"
      onKeyDown={menu.onKeyDown}
      onBlur={menu.onBlur}
    >
      <button
        {...{ [MENU_CONTROL_ATTRIBUTE]: "main" }}
        type="button"
        className={
          isAccessSectionActive
            ? "portal-sidebar__link portal-sidebar__link--active"
            : "portal-sidebar__link"
        }
        aria-expanded={open}
        aria-controls={submenuId}
        title={collapsed ? label : undefined}
        onClick={(event) => menu.toggleFrom(event.currentTarget)}
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

      <ul id={submenuId} ref={submenuRef} className="portal-sidebar__submenu" hidden={!open}>
        {items.map((item) => {
          const active = item.isActive?.(location.pathname)
          return (
            <li key={item.to}>
              {item.unavailableReason !== undefined ? (
                <DisabledNavItem
                  label={item.label}
                  reason={item.unavailableReason}
                  collapsed={collapsed}
                />
              ) : active !== undefined ? (
                <Link
                  className={
                    active
                      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
                      : "portal-sidebar__sublink"
                  }
                  aria-current={active ? "page" : undefined}
                  to={item.to}
                  state={navTaskState(item.to, item.root ?? root)}
                  onClick={menu.onItemClick(item.to)}
                >
                  <span className="portal-sidebar__label">{item.label}</span>
                </Link>
              ) : (
                <NavLink
                  end={item.end}
                  className={subLinkClassName}
                  to={item.to}
                  state={navTaskState(item.to, item.root ?? root)}
                  onClick={menu.onItemClick(item.to)}
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
