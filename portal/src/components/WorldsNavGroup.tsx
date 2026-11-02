import { useEffect, useId, useRef, useState } from "react"
import type {
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from "react"
import { NavLink, useLocation } from "react-router"
import { ChevronDown, Landmark } from "lucide-react"
import { DisabledNavItem } from "./DisabledNavItem"
import {
  NOT_AVAILABLE_FOR_ACCOUNT,
  SELECT_TIMELINE_FIRST,
  SELECT_WORLD_FIRST,
} from "./navigationReasons"

interface WorldsNavGroupProps {
  // The one world whose routes are nested, already verified against the
  // authorized bootstrap by the caller, or null. Never a raw route ID.
  activeWorldId: string | null
  // The timeline the route selects (a timeline route, or the route campaign's
  // timeline), already confirmed against authorized data, or null.
  activeTimelineId: string | null
  // The resolved campaign's world page, when a campaign resolves to this world.
  campaignWorldPath: string | null
  // From the bootstrap's server-computed `global_capabilities` only.
  canCreateWorld: boolean
  // True when the active world's own server-computed capabilities let the
  // caller author it. A view-only world keeps its read-only overview and
  // timeline list; timeline-authoring routes stay visible but disabled.
  canAuthorWorld: boolean
  // From the active world's own server-computed capabilities: `world.share` (Owner with system
  // GM) and `world.canon.read` (any role that may read published canon).
  canShareWorld: boolean
  canReadCanon: boolean
  collapsed: boolean
  onNavigate: () => void
}

// The single world-navigation group: the authorized worlds collection,
// creation (server-authorized only), and — when a world context exists — that
// world's routes. Same disclosure pattern as AccessNavGroup: an entry the
// caller may not use stays in its slot as a DisabledNavItem (never an anchor)
// rather than disappearing.
export function WorldsNavGroup({
  activeWorldId,
  activeTimelineId,
  campaignWorldPath,
  canCreateWorld,
  canAuthorWorld,
  canShareWorld,
  canReadCanon,
  collapsed,
  onNavigate,
}: WorldsNavGroupProps) {
  const location = useLocation()
  const isWorldsSectionActive =
    location.pathname === "/worlds" ||
    location.pathname.startsWith("/worlds/") ||
    (campaignWorldPath !== null &&
      (location.pathname === campaignWorldPath ||
        location.pathname.startsWith(`${campaignWorldPath}/`)))

  // Read once on mount so a direct load of a world route starts open, while
  // choosing a child (which closes it) is not undone by the route becoming
  // active underneath it.
  const [open, setOpen] = useState(() => isWorldsSectionActive)
  const containerRef = useRef<HTMLLIElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const firstItemRef = useRef<HTMLAnchorElement>(null)
  // Focus moves into the submenu only when the user opens it.
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

      setOpen(false)
    }

    document.addEventListener("pointerdown", handlePointerDown)

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
    }
  }, [open])

  function handleKeyDown(event: ReactKeyboardEvent<HTMLLIElement>): void {
    if (event.key === "Escape" && open) {
      // Handled here so it never also closes the mobile drawer.
      event.stopPropagation()
      setOpen(false)
      buttonRef.current?.focus()
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

  const worldPath = activeWorldId === null ? null : `/worlds/${activeWorldId}`

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
          isWorldsSectionActive
            ? "portal-sidebar__link portal-sidebar__link--active"
            : "portal-sidebar__link"
        }
        aria-expanded={open}
        aria-controls={submenuId}
        title={collapsed ? "Worlds" : undefined}
        onClick={() => {
          if (!open) {
            focusOnOpenRef.current = true
          }
          setOpen((current) => !current)
        }}
      >
        <Landmark className="portal-sidebar__icon" aria-hidden="true" />
        <span className="portal-sidebar__label">Worlds</span>
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
        <li>
          <NavLink
            ref={firstItemRef}
            end
            className={subLinkClassName}
            to="/worlds"
            onClick={handleChildActivated}
          >
            <span className="portal-sidebar__label">All worlds</span>
          </NavLink>
        </li>
        <li>
          {canCreateWorld ? (
            <NavLink
              end
              className={subLinkClassName}
              to="/worlds/new"
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">New world</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="New world"
              reason={NOT_AVAILABLE_FOR_ACCOUNT}
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {worldPath !== null ? (
            <NavLink
              end
              className={subLinkClassName}
              to={worldPath}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">World overview</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="World overview"
              reason={SELECT_WORLD_FIRST}
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {worldPath !== null ? (
            <NavLink
              end
              className={subLinkClassName}
              to={`${worldPath}/timelines`}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">Timelines</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="Timelines"
              reason={SELECT_WORLD_FIRST}
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {worldPath !== null && activeTimelineId !== null && canAuthorWorld ? (
            <NavLink
              className={subLinkClassName}
              to={`${worldPath}/timelines/${activeTimelineId}`}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">Timeline overview</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="Timeline overview"
              reason={
                worldPath !== null && activeTimelineId !== null
                  ? NOT_AVAILABLE_FOR_ACCOUNT
                  : SELECT_TIMELINE_FIRST
              }
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {worldPath !== null && canReadCanon ? (
            <NavLink
              end
              className={subLinkClassName}
              to={`${worldPath}/canon`}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">Published canon</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="Published canon"
              reason={worldPath === null ? SELECT_WORLD_FIRST : NOT_AVAILABLE_FOR_ACCOUNT}
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {worldPath !== null && canShareWorld ? (
            <NavLink
              end
              className={subLinkClassName}
              to={`${worldPath}/sharing`}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">Sharing</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="Sharing"
              reason={worldPath === null ? SELECT_WORLD_FIRST : NOT_AVAILABLE_FOR_ACCOUNT}
              collapsed={collapsed}
            />
          )}
        </li>
        <li>
          {campaignWorldPath !== null ? (
            <NavLink
              className={subLinkClassName}
              to={campaignWorldPath}
              onClick={handleChildActivated}
            >
              <span className="portal-sidebar__label">Campaign world</span>
            </NavLink>
          ) : (
            <DisabledNavItem
              label="Campaign world"
              reason="Select a campaign first"
              collapsed={collapsed}
            />
          )}
        </li>
      </ul>
    </li>
  )
}
