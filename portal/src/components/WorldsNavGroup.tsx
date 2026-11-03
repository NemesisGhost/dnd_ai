import { NavLink, useLocation } from "react-router"
import { Landmark } from "lucide-react"
import { DisabledNavItem } from "./DisabledNavItem"
import {
  NOT_AVAILABLE_FOR_ACCOUNT,
  SELECT_TIMELINE_FIRST,
  SELECT_WORLD_FIRST,
} from "./navigationReasons"
import { SplitNavGroup } from "./SplitNavGroup"
import { navTaskState } from "../navigation/navStart"
import type { PrimaryAction } from "../navigation/navbarDestinations"

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
  // False when the world is known only through the selection and the caller is not known to hold
  // `world.view` on it: its overview and timeline list are then offered as unavailable.
  canViewWorld: boolean
  // What the main control does (navigation/navbarDestinations.worldAction).
  action: PrimaryAction
  collapsed: boolean
  onNavigate: () => void
}

// The single world-navigation group: a main control that opens the selected world's details (or toggles the
// menu where the person already is, or nothing applicable is selected) and a separate disclosure; the menu
// holds the authorized worlds collection, creation (server-authorized only), and — when a world is
// selected — that world's routes. An entry the caller may not use stays in its slot as a DisabledNavItem
// (never an anchor) rather than disappearing.
export function WorldsNavGroup({
  activeWorldId,
  activeTimelineId,
  campaignWorldPath,
  canCreateWorld,
  canAuthorWorld,
  canShareWorld,
  canReadCanon,
  canViewWorld,
  action,
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

  function subLinkClassName({ isActive }: { isActive: boolean }): string {
    return isActive
      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
      : "portal-sidebar__sublink"
  }

  const worldPath = activeWorldId === null ? null : `/worlds/${activeWorldId}`

  return (
    <SplitNavGroup
      icon={Landmark}
      label="World"
      noun="world"
      action={action}
      sectionActive={isWorldsSectionActive}
      // Read once on mount so a direct load of a world route starts open.
      initialOpen={isWorldsSectionActive}
      collapsed={collapsed}
      onNavigate={onNavigate}
    >
      {(menu) => (
        <>
          <li>
            <NavLink
              end
              className={subLinkClassName}
              to="/worlds"
              onClick={menu.onItemClick("/worlds")}
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
                onClick={menu.onItemClick("/worlds/new")}
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
            {worldPath !== null && canViewWorld ? (
              <NavLink
                end
                className={subLinkClassName}
                to={worldPath}
                state={navTaskState(worldPath, "world")}
                onClick={menu.onItemClick(worldPath)}
              >
                <span className="portal-sidebar__label">World overview</span>
              </NavLink>
            ) : (
              <DisabledNavItem
                label="World overview"
                reason={worldPath === null ? SELECT_WORLD_FIRST : NOT_AVAILABLE_FOR_ACCOUNT}
                collapsed={collapsed}
              />
            )}
          </li>
          <li>
            {worldPath !== null && canViewWorld ? (
              <NavLink
                end
                className={subLinkClassName}
                to={`${worldPath}/timelines`}
                state={navTaskState(`${worldPath}/timelines`, "world")}
                onClick={menu.onItemClick(`${worldPath}/timelines`)}
              >
                <span className="portal-sidebar__label">Timelines</span>
              </NavLink>
            ) : (
              <DisabledNavItem
                label="Timelines"
                reason={worldPath === null ? SELECT_WORLD_FIRST : NOT_AVAILABLE_FOR_ACCOUNT}
                collapsed={collapsed}
              />
            )}
          </li>
          <li>
            {worldPath !== null && activeTimelineId !== null && canAuthorWorld ? (
              <NavLink
                className={subLinkClassName}
                to={`${worldPath}/timelines/${activeTimelineId}`}
                state={navTaskState(`${worldPath}/timelines/${activeTimelineId}`, "world")}
                onClick={menu.onItemClick(`${worldPath}/timelines/${activeTimelineId}`)}
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
                state={navTaskState(`${worldPath}/canon`, "world")}
                onClick={menu.onItemClick(`${worldPath}/canon`)}
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
                state={navTaskState(`${worldPath}/sharing`, "world")}
                onClick={menu.onItemClick(`${worldPath}/sharing`)}
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
                state={navTaskState(campaignWorldPath, "world")}
                onClick={menu.onItemClick(campaignWorldPath)}
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
        </>
      )}
    </SplitNavGroup>
  )
}
