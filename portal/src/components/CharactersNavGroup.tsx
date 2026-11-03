import { NavLink } from "react-router"
import { Users } from "lucide-react"
import { DisabledNavItem } from "./DisabledNavItem"
import { SELECT_CAMPAIGN_FIRST, SELECT_CHARACTER_FIRST } from "./navigationReasons"
import { SplitNavGroup } from "./SplitNavGroup"
import { navTaskState } from "../navigation/navStart"
import type { PrimaryAction } from "../navigation/navbarDestinations"

interface CharactersNavGroupProps {
  // The resolved campaign's path (`/app/:id`), or null when none resolves.
  campaignPath: string | null
  // The selected perspective character of that campaign, or null (none selected, or an explicit none).
  character: { characterId: string; name: string } | null
  // What the main control does (navigation/navbarDestinations.charactersAction).
  action: PrimaryAction
  // Whether the current task is a Characters task.
  sectionActive: boolean
  collapsed: boolean
  onNavigate: () => void
}

// The Characters control: a main control that opens the selected character's record, or toggles the menu
// where the person is already in Characters or no character is selected, and a separate disclosure. The
// menu offers the selected character (when present) and the list of every character the person may see.
// It offers no create action: that stays on the Characters page until the create-action decision
// (PD-8) is made.
export function CharactersNavGroup({
  campaignPath,
  character,
  action,
  sectionActive,
  collapsed,
  onNavigate,
}: CharactersNavGroupProps) {
  const subLinkClassName = ({ isActive }: { isActive: boolean }): string =>
    isActive
      ? "portal-sidebar__sublink portal-sidebar__sublink--active"
      : "portal-sidebar__sublink"

  return (
    <SplitNavGroup
      icon={Users}
      label="Characters"
      noun="characters"
      action={action}
      sectionActive={sectionActive}
      initialOpen={false}
      collapsed={collapsed}
      onNavigate={onNavigate}
    >
      {(menu) => (
        <>
          <li>
            {character !== null && campaignPath !== null ? (
              <NavLink
                end
                className={subLinkClassName}
                to={`${campaignPath}/characters/${character.characterId}`}
                state={navTaskState(`${campaignPath}/characters/${character.characterId}`, "characters")}
                onClick={menu.onItemClick(`${campaignPath}/characters/${character.characterId}`)}
              >
                <span className="portal-sidebar__label">Selected character</span>
                <span className="portal-sidebar__detail">{character.name}</span>
              </NavLink>
            ) : (
              <DisabledNavItem
                label="Selected character"
                reason={campaignPath === null ? SELECT_CAMPAIGN_FIRST : SELECT_CHARACTER_FIRST}
                collapsed={collapsed}
              />
            )}
          </li>
          <li>
            {campaignPath !== null ? (
              <NavLink
                end
                className={subLinkClassName}
                to={`${campaignPath}/characters/all`}
                state={navTaskState(`${campaignPath}/characters/all`, "characters")}
                onClick={menu.onItemClick(`${campaignPath}/characters/all`)}
              >
                <span className="portal-sidebar__label">All characters</span>
              </NavLink>
            ) : (
              <DisabledNavItem
                label="All characters"
                reason={SELECT_CAMPAIGN_FIRST}
                collapsed={collapsed}
              />
            )}
          </li>
        </>
      )}
    </SplitNavGroup>
  )
}
