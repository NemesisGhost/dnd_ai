import { useEffect, useRef } from "react"
import type { KeyboardEvent as ReactKeyboardEvent } from "react"
import { NavLink, useMatch } from "react-router"
import type { LucideIcon } from "lucide-react"
import {
  BookOpen,
  CalendarDays,
  LayoutList,
  MessageCircleQuestion,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react"
import { useSession } from "../context/SessionContext"
import { useSelectCampaign } from "../hooks/useSelectCampaign"
import { useSidebarCollapsed } from "../hooks/useSidebarCollapsed"
import type { NavigationDrawerControl } from "../hooks/useNavigationDrawer"
import { resolveNavigationCampaign } from "../utils/resolveNavigationCampaign"
import { AccessNavGroup } from "./AccessNavGroup"
import { CampaignHomeNavGroup } from "./CampaignHomeNavGroup"
import { DisabledNavItem } from "./DisabledNavItem"
import { SELECT_CAMPAIGN_FIRST } from "./navigationReasons"
import { WorldsNavGroup } from "./WorldsNavGroup"

interface NavigationItem {
  path: string
  label: string
  icon: LucideIcon
}

// Campaign Home is rendered by CampaignHomeNavGroup; the campaign world page
// lives under the Worlds group (WorldsNavGroup).
const campaignNavigationItems: NavigationItem[] = [
  { path: "characters", label: "Characters", icon: Users },
  { path: "quests", label: "Quests", icon: ScrollText },
  { path: "sessions", label: "Sessions", icon: CalendarDays },
  { path: "knowledge", label: "Knowledge", icon: BookOpen },
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
// Campaign-specific links target the *resolved* authorized campaign (route
// campaign, else last visited, else startup) — never a guessed or stale ID.
export function PortalSidebar({ drawer }: PortalSidebarProps) {
  const { state } = useSession()
  const routeMatch = useMatch("/app/:campaignId/*")
  const routeCampaignId = routeMatch?.params.campaignId
  const worldRouteMatch = useMatch("/worlds/:worldId/*")
  const [collapsed, toggleCollapsed] = useSidebarCollapsed()
  const selectCampaign = useSelectCampaign(routeCampaignId)
  const navigationRef = useRef<HTMLElement>(null)
  const { open: drawerOpen, closeAndFocusToggle, close } = drawer

  useEffect(() => {
    if (!drawerOpen) {
      return
    }

    // Opening the drawer moves focus to its first item.
    navigationRef.current
      ?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ?.focus()

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        closeAndFocusToggle()
      }
    }

    document.addEventListener("keydown", handleKeyDown)

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [drawerOpen, closeAndFocusToggle])

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
      : resolveNavigationCampaign(bootstrap, routeCampaignId)
  const authorizedRouteCampaignId =
    bootstrap?.campaigns.some(
      (campaign) => campaign.campaign_id === routeCampaignId,
    ) === true
      ? routeCampaignId
      : undefined
  const campaignPath =
    resolvedCampaign === null ? null : `/app/${resolvedCampaign.campaign_id}`

  // World context comes only from worlds the bootstrap already authorizes:
  // an authorized world route, else the authorized route campaign's world. A
  // raw route world ID that is not in the bootstrap exposes nothing.
  const authorizedRouteCampaign = bootstrap?.campaigns.find(
    (campaign) => campaign.campaign_id === authorizedRouteCampaignId,
  )
  const routeWorldId = worldRouteMatch?.params.worldId
  const activeWorldId =
    routeWorldId !== undefined &&
    bootstrap?.campaigns.some((campaign) => campaign.world_id === routeWorldId)
      ? routeWorldId
      : (authorizedRouteCampaign?.world_id ?? null)
  const activeTimelineCampaign =
    activeWorldId === null
      ? undefined
      : resolvedCampaign?.world_id === activeWorldId
        ? resolvedCampaign
        : bootstrap?.campaigns.find(
            (campaign) => campaign.world_id === activeWorldId,
          )
  const activeTimelineId = activeTimelineCampaign?.timeline_id ?? null

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
                  onClick={close}
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
                collapsed={collapsed}
                onSelectCampaign={selectCampaign}
                onNavigate={close}
              />

              <WorldsNavGroup
                activeWorldId={activeWorldId}
                activeTimelineId={activeTimelineId}
                campaignWorldPath={
                  campaignPath === null ? null : `${campaignPath}/world`
                }
                canCreateWorld={
                  bootstrap.global_capabilities?.includes("world.create") ===
                  true
                }
                collapsed={collapsed}
                onNavigate={close}
              />

              {campaignNavigationItems.map((item) => {
                const Icon = item.icon
                return (
                  <li key={item.path}>
                    {campaignPath === null ? (
                      <DisabledNavItem
                        icon={Icon}
                        label={item.label}
                        reason={SELECT_CAMPAIGN_FIRST}
                        collapsed={collapsed}
                      />
                    ) : (
                      <NavLink
                        className={linkClassName}
                        to={`${campaignPath}/${item.path}`}
                        title={collapsed ? item.label : undefined}
                        onClick={close}
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
                    title={collapsed ? "Ask" : undefined}
                    onClick={close}
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
