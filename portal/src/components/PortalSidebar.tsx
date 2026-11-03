import { useEffect, useRef } from "react"
import type { KeyboardEvent as ReactKeyboardEvent } from "react"
import { NavLink, useLocation, useMatch } from "react-router"
import type { LucideIcon } from "lucide-react"
import {
  BookOpen,
  CalendarDays,
  ClipboardCheck,
  LayoutList,
  MessageCircleQuestion,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ShieldCheck,
  UsersRound,
} from "lucide-react"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import { useSidebarCollapsed } from "../hooks/useSidebarCollapsed"
import type { NavigationDrawerControl } from "../hooks/useNavigationDrawer"
import { selectionFor, useSelectedContextSnapshot } from "../navigation/selectedContextStore"
import { resolveNavigationCampaign } from "../utils/resolveNavigationCampaign"
import { navTaskState } from "../navigation/navStart"
import {
  campaignAction,
  charactersAction,
  selectedCharacter,
  worldAction,
} from "../navigation/navbarDestinations"
import { resolveTask } from "../navigation/resolveTask"
import type { NavRoot } from "../navigation/routeMeta"
import { navigationQuestionActive, registerFocusFallback } from "../hooks/navigationHolds"
import { canCreateWorlds } from "../utils/worldAccess"
import { AccessNavGroup } from "./AccessNavGroup"
import { CampaignHomeNavGroup } from "./CampaignHomeNavGroup"
import { CharactersNavGroup } from "./CharactersNavGroup"
import { DisabledNavItem } from "./DisabledNavItem"
import { FALLBACK_DRAWER_TOGGLE, useAcceptedNavigation } from "./useSidebarMenu"
import { ItemsNavGroup } from "./ItemsNavGroup"
import { KnowledgeNavGroup } from "./KnowledgeNavGroup"
import { NEEDS_WORLD_ROLE, SELECT_CAMPAIGN_FIRST } from "./navigationReasons"
import { WorldsNavGroup } from "./WorldsNavGroup"

interface NavigationItem {
  path: string
  label: string
  // The task root this Navbar item starts (docs/UI_DESIGN.md §4.8).
  root: NavRoot
  icon: LucideIcon
  // Shown only on a campaign that grants this capability.
  capability?: string
  // Offered as a link only where the caller also holds this capability on the campaign's world
  // (the bootstrap's server-computed list); otherwise shown as unavailable, never requested.
  worldCapability?: string
}

// Campaign is rendered by CampaignHomeNavGroup, World by WorldsNavGroup and Characters by
// CharactersNavGroup (each a split control); the campaign world page lives under the World menu.
const campaignNavigationItems: NavigationItem[] = [
  { path: "parties", label: "Parties", root: "parties", icon: UsersRound },
  { path: "quests", label: "Quests", root: "quests", icon: ScrollText },
  { path: "sessions", label: "Sessions", root: "sessions", icon: CalendarDays },
  { path: "knowledge", label: "Knowledge", root: "knowledge", icon: BookOpen },
  {
    path: "review",
    root: "review",
    label: "Review queue",
    icon: ClipboardCheck,
    capability: "canon.edit",
    worldCapability: "world.canon.read_private",
  },
  {
    path: "items",
    root: "items",
    label: "Items",
    icon: Package,
    capability: "canon.edit",
  },
]

const NAVIGATION_LIST_ID = "main-navigation-list"
export const MAIN_NAVIGATION_ID = "main-navigation"

const FOCUSABLE_SELECTOR =
  "a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])"

interface PortalSidebarProps {
  drawer: NavigationDrawerControl
}

// The single persistent authenticated navigation (UI_DESIGN §4). Rendered
// by AuthenticatedAppLayout outside the session boundary, so it stays
// mounted on every authenticated route and through the loading state a
// campaign-scope change causes. It reads the session directly:
//
//   loading / error   frame + "View all campaigns" + collapse control, no
//                     campaign names and no campaign-specific links;
//   unauthenticated   nothing (the boundary is redirecting to /login);
//   authenticated     full content.
//
// Campaign-specific links target the *resolved* authorized campaign: the
// route campaign; else, on a world route, the selected campaign if it belongs
// to that world; else the selected campaign. With nothing selected they are
// disabled; the last-visited and startup campaigns are never used as a guess
// (UI_DESIGN §4.5, §4.8).
export function PortalSidebar({ drawer }: PortalSidebarProps) {
  const { state } = useSession()
  const retained = useSelectedContextSnapshot()
  const routeMatch = useMatch("/app/:campaignId/*")
  const routeCampaignId = routeMatch?.params.campaignId
  const [collapsed, toggleCollapsed] = useSidebarCollapsed()
  // World and timeline context come from the route-derived hierarchy, which
  // confirms them against server data (WorkspaceHierarchyProvider) — never a
  // raw route ID.
  const {
    activeWorldId,
    activeTimelineId,
    authoringWorldId,
    authoringTimelineId,
    authoringWorldAccess,
    routeNamesWorld,
    routeNamesTimeline,
    world,
  } = useWorkspaceHierarchy()
  // The caller's capabilities on the world the route confirmed, from the server's own read.
  const worldHas = (capability: string): boolean =>
    world?.kind === "ready" && world.data.capabilities.includes(capability)
  const navigationRef = useRef<HTMLElement>(null)
  const { open: drawerOpen, closeAndFocusToggle, close, toggleElement } = drawer
  const location = useLocation()
  // The drawer closes when a navigation made from it is *accepted* (the location reaches what was
  // asked for), not on the click: the page's unsaved-changes question may still refuse it, and Stay
  // leaves the drawer as it was (CTX-4). The groups do the same for their menus.
  const plainLinks = useAcceptedNavigation({ onAccepted: close, opener: () => null })

  useEffect(() => {
    if (!drawerOpen) {
      return
    }

    // Opening the drawer moves focus to its first item.
    navigationRef.current
      ?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ?.focus()

    function handleKeyDown(event: KeyboardEvent): void {
      // While the navigation question is open its dialog owns Escape (it means Stay): the drawer stays.
      if (event.key === "Escape" && !navigationQuestionActive()) {
        closeAndFocusToggle()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    // The last place a Stay may put focus when nothing nearer is usable.
    const releaseFallback = registerFocusFallback(FALLBACK_DRAWER_TOGGLE, toggleElement)

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      releaseFallback()
    }
  }, [drawerOpen, closeAndFocusToggle, toggleElement])

  if (state.status === "unauthenticated") {
    return null
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLElement>): void {
    if (event.key !== "Tab" || !drawerOpen || !isDrawerMode()) {
      return
    }

    // Trap Tab inside the open drawer: wrap at either end.
    const focusable = Array.from(
      navigationRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ??
        [],
    ).filter((element) => element.offsetParent !== null || !hasLayout())

    if (focusable.length === 0) {
      return
    }

    const first = focusable[0]!
    const last = focusable[focusable.length - 1]!

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const navigationClassName = [
    "portal-sidebar",
    collapsed ? "portal-sidebar--collapsed" : null,
    drawerOpen ? "portal-sidebar--mobile-open" : null,
  ]
    .filter(Boolean)
    .join(" ")

  const linkClassName = ({ isActive }: { isActive: boolean }): string =>
    isActive
      ? "portal-sidebar__link portal-sidebar__link--active"
      : "portal-sidebar__link"

  const bootstrap = state.status === "authenticated" ? state.bootstrap : null
  const resolvedCampaign =
    bootstrap === null
      ? null
      : resolveNavigationCampaign(
          bootstrap,
          routeCampaignId,
          {
            routeNamesWorld,
            routeNamesTimeline,
            activeWorldId,
            activeTimelineId,
          },
          selectionFor(retained, bootstrap).campaignId,
        )
  const authorizedRouteCampaignId =
    bootstrap?.campaigns.some(
      (campaign) => campaign.campaign_id === routeCampaignId,
    ) === true
      ? routeCampaignId
      : undefined
  const campaignPath =
    resolvedCampaign === null ? null : `/app/${resolvedCampaign.campaign_id}`

  // The caller's world capabilities for the campaign the links point at, from the bootstrap
  // (server-computed). Fails closed: no list, no link to a page that would only be refused.
  const worldRoleHas = (capability: string): boolean =>
    resolvedCampaign?.world_capabilities?.includes(capability) === true

  // The explicit selection this tab retains, for this user only; and the task the shown page belongs to.
  const selection = selectionFor(retained, bootstrap)
  const situation = {
    pathname: location.pathname,
    currentRoot: resolveTask(location.pathname, location.state)?.task.root ?? null,
  }

  // The selected world. A world the route confirms is the route's own scope. Otherwise it is the retained
  // selection, and only while it is compatible with the retained campaign: a campaign that is gone or
  // belongs to another world makes it no selection at all.
  const routeWorldId = authoringWorldAccess === "none" ? null : authoringWorldId
  const retainedCampaign =
    bootstrap === null || selection.campaignId === null
      ? null
      : (bootstrap.campaigns.find((campaign) => campaign.campaign_id === selection.campaignId) ?? null)
  const retainedWorldId =
    selection.worldId === null
      ? null
      : selection.campaignId === null
        ? selection.worldId
        : retainedCampaign?.world_id === selection.worldId
          ? selection.worldId
          : null
  const selectedWorldId = routeWorldId ?? retainedWorldId
  // The campaign of that world the person can act in: the one the links already resolve, else the retained one.
  const worldCampaign =
    selectedWorldId === null
      ? null
      : [resolvedCampaign, retainedCampaign].find((campaign) => campaign?.world_id === selectedWorldId) ?? null
  // What the caller may do on it: the server's own read of the world when the page has one, else the
  // capabilities the bootstrap lists for a campaign of that world. Unknown means unavailable, never guessed.
  const selectedWorldCapabilities: readonly string[] | null =
    selectedWorldId === null
      ? null
      : world?.kind === "ready" && world.data.world_id === selectedWorldId
        ? world.data.capabilities
        : (worldCampaign?.world_capabilities ?? null)
  const selectedWorldName =
    selectedWorldId === null
      ? null
      : world?.kind === "ready" && world.data.world_id === selectedWorldId
        ? world.data.name
        : (worldCampaign?.world_name ?? null)
  const worldHasSelected = (capability: string): boolean =>
    selectedWorldCapabilities?.includes(capability) === true
  const selectedCharacterRecord = selectedCharacter(resolvedCampaign, selection)

  const toggleLabel = collapsed ? "Expand navigation" : "Collapse navigation"
  const CollapseIcon = collapsed ? PanelLeftOpen : PanelLeftClose

  return (
    <>
      {drawerOpen && (
        <button
          type="button"
          className="portal-sidebar__backdrop"
          aria-label="Dismiss navigation"
          onClick={closeAndFocusToggle}
        />
      )}
      <nav
        id={MAIN_NAVIGATION_ID}
        ref={navigationRef}
        className={navigationClassName}
        aria-label="Main"
        onKeyDown={handleKeyDown}
      >
        <ul
          id={NAVIGATION_LIST_ID}
          className="portal-sidebar__list"
          aria-busy={state.status === "loading" ? true : undefined}
        >
          {bootstrap === null ? (
            <>
              {state.status === "loading" && (
                <li className="portal-sidebar__note" role="status">
                  Loading navigation…
                </li>
              )}
              <li>
                <NavLink
                  end
                  className={linkClassName}
                  to="/campaigns"
                  title={collapsed ? "All campaigns" : undefined}
                  onClick={(event) => plainLinks.begin(event, "/campaigns")}
                >
                  <LayoutList
                    className="portal-sidebar__icon"
                    aria-hidden="true"
                  />
                  <span className="portal-sidebar__label">
                    View all campaigns
                  </span>
                </NavLink>
              </li>
            </>
          ) : (
            <>
              <CampaignHomeNavGroup
                campaigns={bootstrap.campaigns}
                resolvedCampaign={resolvedCampaign}
                authorizedRouteCampaignId={authorizedRouteCampaignId}
                action={campaignAction(resolvedCampaign, situation)}
                sectionActive={situation.currentRoot === "campaign"}
                collapsed={collapsed}
                onNavigate={close}
              />

              <WorldsNavGroup
                activeWorldId={selectedWorldId}
                activeTimelineId={routeWorldId === null ? null : authoringTimelineId}
                canAuthorWorld={
                  routeWorldId === null
                    ? worldHasSelected("timeline.manage")
                    : authoringWorldAccess === "edit" || worldHas("timeline.manage")
                }
                canShareWorld={
                  routeWorldId === null ? worldHasSelected("world.share") : worldHas("world.share")
                }
                canReadCanon={
                  routeWorldId === null
                    ? worldHasSelected("world.canon.read")
                    : worldHas("world.canon.read")
                }
                canViewWorld={routeWorldId !== null || worldHasSelected("world.view")}
                action={worldAction(
                  selectedWorldId === null
                    ? null
                    : {
                        worldId: selectedWorldId,
                        name: selectedWorldName,
                        canView: worldHasSelected("world.view"),
                        campaignId: worldCampaign?.campaign_id ?? null,
                      },
                  situation,
                )}
                campaignWorldPath={
                  campaignPath === null ? null : `${campaignPath}/world`
                }
                canCreateWorld={canCreateWorlds(bootstrap)}
                collapsed={collapsed}
                onNavigate={close}
              />

              <CharactersNavGroup
                campaignPath={campaignPath}
                character={selectedCharacterRecord}
                action={charactersAction(resolvedCampaign, selectedCharacterRecord, situation)}
                sectionActive={situation.currentRoot === "characters"}
                collapsed={collapsed}
                onNavigate={close}
              />

              {campaignNavigationItems
                .filter(
                  (item) =>
                    item.capability === undefined ||
                    resolvedCampaign?.capabilities.includes(item.capability) ===
                      true,
                )
                .map((item) => {
                const Icon = item.icon
                // Knowledge expands into Claims and Member preview for anyone who can
                // preview a member; everyone else keeps the plain link below.
                if (
                  item.path === "knowledge" &&
                  campaignPath !== null &&
                  resolvedCampaign?.capabilities.includes("access.manage") ===
                    true
                ) {
                  return (
                    <KnowledgeNavGroup
                      key={item.path}
                      campaignPath={campaignPath}
                      collapsed={collapsed}
                      onNavigate={close}
                    />
                  )
                }
                // Items expands into Inventory and Definitions (the capability filter above
                // already limits it to `canon.edit`).
                if (item.path === "items" && campaignPath !== null) {
                  return (
                    <ItemsNavGroup
                      key={item.path}
                      campaignPath={campaignPath}
                      collapsed={collapsed}
                      canOpenDefinitions={worldRoleHas("world.canon.read_private")}
                      onNavigate={close}
                    />
                  )
                }
                return (
                  <li key={item.path}>
                    {campaignPath === null ? (
                      <DisabledNavItem
                        icon={Icon}
                        label={item.label}
                        reason={SELECT_CAMPAIGN_FIRST}
                        collapsed={collapsed}
                      />
                    ) : item.worldCapability !== undefined &&
                      !worldRoleHas(item.worldCapability) ? (
                      <DisabledNavItem
                        icon={Icon}
                        label={item.label}
                        reason={NEEDS_WORLD_ROLE}
                        collapsed={collapsed}
                      />
                    ) : (
                      <NavLink
                        className={linkClassName}
                        to={`${campaignPath}/${item.path}`}
                        state={navTaskState(`${campaignPath}/${item.path}`, item.root)}
                        title={collapsed ? item.label : undefined}
                        onClick={(event) =>
                          plainLinks.begin(event, `${campaignPath}/${item.path}`)
                        }
                      >
                        <Icon
                          className="portal-sidebar__icon"
                          aria-hidden="true"
                        />
                        <span className="portal-sidebar__label">
                          {item.label}
                        </span>
                      </NavLink>
                    )}
                  </li>
                )
              })}

              <li>
                {campaignPath === null ? (
                  <DisabledNavItem
                    icon={MessageCircleQuestion}
                    label="Ask"
                    reason={SELECT_CAMPAIGN_FIRST}
                    collapsed={collapsed}
                  />
                ) : bootstrap.features.ask ? (
                  <NavLink
                    className={linkClassName}
                    to={`${campaignPath}/ask`}
                    state={navTaskState(`${campaignPath}/ask`, "campaign")}
                    title={collapsed ? "Ask" : undefined}
                    onClick={(event) => plainLinks.begin(event, `${campaignPath}/ask`)}
                  >
                    <MessageCircleQuestion
                      className="portal-sidebar__icon"
                      aria-hidden="true"
                    />
                    <span className="portal-sidebar__label">Ask</span>
                  </NavLink>
                ) : (
                  <DisabledNavItem
                    icon={MessageCircleQuestion}
                    label="Ask"
                    reason="Unavailable until Phase 12 is verified"
                    collapsed={collapsed}
                  />
                )}
              </li>

              {/* The slot exists for anyone who can manage access on at least
                  one authorized campaign (a fact about the caller, stable
                  across routes); the group is usable only on a campaign that
                  grants it. */}
              {bootstrap.campaigns.some((campaign) =>
                campaign.capabilities.includes("access.manage"),
              ) &&
                (campaignPath !== null &&
                resolvedCampaign?.capabilities.includes("access.manage") ===
                  true ? (
                  <AccessNavGroup
                    campaignPath={campaignPath}
                    collapsed={collapsed}
                    onNavigate={close}
                  />
                ) : (
                  <li>
                    <DisabledNavItem
                      icon={ShieldCheck}
                      label="Access"
                      reason={
                        campaignPath === null
                          ? SELECT_CAMPAIGN_FIRST
                          : "Unavailable for this campaign"
                      }
                      collapsed={collapsed}
                    />
                  </li>
                ))}
            </>
          )}

          <li className="portal-sidebar__toggle-item">
            <button
              type="button"
              className="portal-sidebar__toggle"
              aria-controls={NAVIGATION_LIST_ID}
              aria-expanded={!collapsed}
              aria-label={toggleLabel}
              onClick={toggleCollapsed}
            >
              <CollapseIcon
                className="portal-sidebar__icon"
                aria-hidden="true"
              />
              <span className="portal-sidebar__label">{toggleLabel}</span>
            </button>
          </li>
        </ul>
      </nav>
    </>
  )
}

// The drawer only exists below the narrow breakpoint (40rem, matching
// App.css). Where matchMedia is unavailable (jsdom) an open drawer is
// treated as a drawer.
function isDrawerMode(): boolean {
  return (
    typeof window.matchMedia !== "function" ||
    window.matchMedia("(max-width: 40rem)").matches
  )
}

// jsdom performs no layout, so offsetParent is always null there.
function hasLayout(): boolean {
  return typeof window.matchMedia === "function"
}
