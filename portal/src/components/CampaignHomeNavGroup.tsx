import { Link, NavLink, useLocation } from "react-router"
import { House } from "lucide-react"
import type { CampaignContext } from "../types/bootstrap"
import { DisabledNavItem } from "./DisabledNavItem"
import { SELECT_CAMPAIGN_FIRST } from "./navigationReasons"
import { SplitNavGroup } from "./SplitNavGroup"
import { navTaskState } from "../navigation/navStart"
import type { PrimaryAction } from "../navigation/navbarDestinations"

interface CampaignHomeNavGroupProps {
  campaigns: CampaignContext[]
  // The campaign the campaign-specific links target (route campaign, else the
  // selected campaign; never a last-visited or startup guess), or null when none resolves.
  resolvedCampaign: CampaignContext | null
  // The route's campaign, only when it is in the current bootstrap — drives
  // aria-current on its list entry. Never a fallback-resolved campaign.
  authorizedRouteCampaignId: string | undefined
  // What the main control does (navigation/navbarDestinations.campaignAction).
  action: PrimaryAction
  // Whether the current task is a Campaign task (Campaign Home, setup and settings).
  sectionActive: boolean
  collapsed: boolean
  onNavigate: () => void
}

// The Campaign control (UI_DESIGN §4.5): a main control that opens the selected campaign's Home, or toggles
// the menu where Home is already where the person is or no campaign is selected, and a separate disclosure.
// The menu lists the selected campaign's Home, every authorized campaign, and "View all campaigns".
export function CampaignHomeNavGroup({
  campaigns,
  resolvedCampaign,
  authorizedRouteCampaignId,
  action,
  sectionActive,
  collapsed,
  onNavigate,
}: CampaignHomeNavGroupProps) {
  const location = useLocation()
  const subLinkClassName = ({ isActive }: { isActive: boolean }): string =>
    isActive
      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
      : "portal-sidebar__sublink"

  return (
    <SplitNavGroup
      icon={House}
      label="Campaign"
      noun="campaign"
      action={action}
      sectionActive={sectionActive}
      // Open on the complete campaign list route, closed elsewhere.
      initialOpen={location.pathname === "/campaigns"}
      collapsed={collapsed}
      onNavigate={onNavigate}
    >
      {(menu) => (
        <>
          <li>
            {resolvedCampaign !== null ? (
              <NavLink
                end
                className={subLinkClassName}
                to={`/app/${resolvedCampaign.campaign_id}/home`}
                state={navTaskState(`/app/${resolvedCampaign.campaign_id}/home`, "campaign")}
                onClick={menu.onItemClick(`/app/${resolvedCampaign.campaign_id}/home`)}
              >
                <span className="portal-sidebar__label">Campaign Home</span>
              </NavLink>
            ) : (
              <DisabledNavItem
                label="Campaign Home"
                reason={SELECT_CAMPAIGN_FIRST}
                collapsed={collapsed}
              />
            )}
          </li>
          {campaigns.map((campaign) => (
            <li key={campaign.campaign_id}>
              <Link
                className="portal-sidebar__sublink"
                to={`/app/${campaign.campaign_id}/home`}
                state={navTaskState(`/app/${campaign.campaign_id}/home`, "campaign")}
                aria-current={
                  campaign.campaign_id === authorizedRouteCampaignId
                    ? "true"
                    : undefined
                }
                onClick={menu.onItemClick(`/app/${campaign.campaign_id}/home`)}
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
              className={subLinkClassName}
              to="/campaigns"
              onClick={menu.onItemClick("/campaigns")}
            >
              <span className="portal-sidebar__label">View all campaigns</span>
            </NavLink>
          </li>
        </>
      )}
    </SplitNavGroup>
  )
}
