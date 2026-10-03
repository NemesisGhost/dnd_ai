import { useEffect, useId, useRef, useState } from "react"
import type { KeyboardEvent as ReactKeyboardEvent } from "react"
import { Link, NavLink, useLocation } from "react-router"
import { ChevronDown, House, LayoutList } from "lucide-react"
import type { CampaignContext } from "../types/bootstrap"

interface CampaignHomeNavGroupProps {
  campaigns: CampaignContext[]
  // The campaign the campaign-specific links target (route campaign, else
  // last visited, else startup), or null when none resolves.
  resolvedCampaign: CampaignContext | null
  // The route's campaign, only when it is in the current bootstrap — drives
  // aria-current on its list entry. Never a fallback-resolved campaign.
  authorizedRouteCampaignId: string | undefined
  collapsed: boolean
  onSelectCampaign: (campaignId: string) => void
  onNavigate: () => void
}

// Campaign Home plus the authorized-campaign subnavigation and
// "View all campaigns" (UI_DESIGN §4.5). Navigation and disclosure are two
// separate controls: the Campaign Home link navigates, the chevron button
// only discloses the list.
export function CampaignHomeNavGroup({
  campaigns,
  resolvedCampaign,
  authorizedRouteCampaignId,
  collapsed,
  onSelectCampaign,
  onNavigate,
}: CampaignHomeNavGroupProps) {
  const location = useLocation()
  // Open on the complete campaign list route, closed elsewhere; read once
  // so choosing an entry (which navigates) is not undone by the route
  // becoming active underneath it.
  const [open, setOpen] = useState(() => location.pathname === "/campaigns")
  const containerRef = useRef<HTMLLIElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const listId = useId()

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

  const homeLinkClassName = ({ isActive }: { isActive: boolean }): string =>
    isActive
      ? "portal-sidebar__link portal-sidebar__link--active"
      : "portal-sidebar__link"

  if (collapsed) {
    // Icon rail: the Campaign Home link (when a campaign resolves) and a
    // separate link to the complete list; the disclosure needs labels.
    return (
      <>
        {resolvedCampaign !== null && (
          <li>
            <NavLink
              end
              className={homeLinkClassName}
              to={`/app/${resolvedCampaign.campaign_id}/home`}
              title="Campaign Home"
              onClick={onNavigate}
            >
              <House className="portal-sidebar__icon" aria-hidden="true" />
              <span className="portal-sidebar__label">Campaign Home</span>
            </NavLink>
          </li>
        )}
        <li>
          <NavLink
            end
            className={homeLinkClassName}
            to="/campaigns"
            title="All campaigns"
            onClick={onNavigate}
          >
            <LayoutList className="portal-sidebar__icon" aria-hidden="true" />
            <span className="portal-sidebar__label">All campaigns</span>
          </NavLink>
        </li>
      </>
    )
  }

  return (
    <li
      ref={containerRef}
      className="portal-sidebar__campaign-group"
      onKeyDown={handleKeyDown}
    >
      <div className="portal-sidebar__row">
        {resolvedCampaign !== null && (
          <NavLink
            end
            className={homeLinkClassName}
            to={`/app/${resolvedCampaign.campaign_id}/home`}
            onClick={onNavigate}
          >
            <House className="portal-sidebar__icon" aria-hidden="true" />
            <span className="portal-sidebar__label">Campaign Home</span>
          </NavLink>
        )}
        <button
          ref={buttonRef}
          type="button"
          className={
            resolvedCampaign === null
              ? "portal-sidebar__link"
              : "portal-sidebar__link portal-sidebar__link--icon-only"
          }
          aria-expanded={open}
          aria-controls={listId}
          aria-label={resolvedCampaign === null ? undefined : "Choose campaign"}
          onClick={() => setOpen((current) => !current)}
        >
          {resolvedCampaign === null && (
            <>
              <House className="portal-sidebar__icon" aria-hidden="true" />
              <span className="portal-sidebar__label">Choose a campaign</span>
            </>
          )}
          <ChevronDown
            className={
              open
                ? "portal-sidebar__chevron portal-sidebar__chevron--open"
                : "portal-sidebar__chevron"
            }
            aria-hidden="true"
          />
        </button>
      </div>

      <ul id={listId} className="portal-sidebar__submenu" hidden={!open}>
        {campaigns.map((campaign) => (
          <li key={campaign.campaign_id}>
            <Link
              className="portal-sidebar__sublink"
              to={`/app/${campaign.campaign_id}/home`}
              aria-current={
                campaign.campaign_id === authorizedRouteCampaignId
                  ? "true"
                  : undefined
              }
              onClick={() => {
                onSelectCampaign(campaign.campaign_id)
                setOpen(false)
                onNavigate()
              }}
            >
              <span className="portal-sidebar__label">
                {campaign.campaign_name}
              </span>
            </Link>
          </li>
        ))}
        <li>
          <NavLink
            end
            className={({ isActive }) =>
              isActive
                ? "portal-sidebar__sublink portal-sidebar__sublink--active"
                : "portal-sidebar__sublink"
            }
            to="/campaigns"
            onClick={() => {
              setOpen(false)
              onNavigate()
            }}
          >
            <span className="portal-sidebar__label">View all campaigns</span>
          </NavLink>
        </li>
      </ul>
    </li>
  )
}
