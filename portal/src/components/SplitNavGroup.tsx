import { useId } from "react"
import type { MouseEvent as ReactMouseEvent, ReactNode } from "react"
import { Link } from "react-router"
import { ChevronDown } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { navTaskState } from "../navigation/navStart"
import type { PrimaryAction } from "../navigation/navbarDestinations"
import { MENU_CONTROL_ATTRIBUTE, useSidebarMenu } from "./useSidebarMenu"
import type { SidebarMenu } from "./useSidebarMenu"

interface SplitNavGroupProps {
    icon: LucideIcon
    // The visible text: "Campaign", "World" or "Characters".
    label: string
    // Lower case noun for the accessible names: "campaign", "world", "characters".
    noun: string
    action: PrimaryAction
    // Whether the current route lies anywhere in this section (styling only).
    sectionActive: boolean
    initialOpen: boolean
    collapsed: boolean
    onNavigate: () => void
    // The menu's items, as list items. `menu.onItemClick(to)` goes on each link that navigates.
    children: (menu: SidebarMenu) => ReactNode
}

// The Navbar's split control (plan §4.1): a main control and a separate disclosure. Where the main control
// can take the person to the selected context's details it is a link (an ordinary anchor: new tab,
// modified clicks and the guard all behave as for any link); otherwise it is a button that toggles the menu
// and never navigates. The role follows the behavior, so a link never toggles and a button never
// navigates. The disclosure always toggles, so expanding the menu is directly usable in every state. The
// two are siblings, never nested. Open, close and focus rules are `useSidebarMenu`'s, shared with the
// other groups.
export function SplitNavGroup({
    icon: Icon,
    label,
    noun,
    action,
    sectionActive,
    initialOpen,
    collapsed,
    onNavigate,
    children,
}: SplitNavGroupProps) {
    const { menu, containerRef, submenuRef } = useSidebarMenu({ initialOpen, onNavigate })
    const { open } = menu
    const submenuId = useId()
    // The accessible name starts with the visible label, so voice control and screen readers agree with
    // what is on screen (WCAG 2.5.3): "Characters: open Ixamarra", "World: open Mundivita".
    const linkName = action.kind === "link" ? `${label}: open ${action.detail}` : undefined

    const mainClassName = sectionActive
        ? "portal-sidebar__link portal-sidebar__link--active"
        : "portal-sidebar__link"
    const chevronClassName = open
        ? "portal-sidebar__chevron portal-sidebar__chevron--open"
        : "portal-sidebar__chevron"
    const mainContent = (
        <>
            <Icon className="portal-sidebar__icon" aria-hidden="true" />
            <span className="portal-sidebar__label">{label}</span>
        </>
    )

    return (
        <li
            ref={containerRef}
            className="portal-sidebar__access-group portal-sidebar__split-group"
            onKeyDown={menu.onKeyDown}
            onBlur={menu.onBlur}
        >
            <div className="portal-sidebar__row">
                {action.kind === "link" ? (
                    <Link
                        {...{ [MENU_CONTROL_ATTRIBUTE]: "main" }}
                        className={mainClassName}
                        to={action.to}
                        state={navTaskState(action.to, action.root)}
                        aria-label={linkName}
                        title={collapsed ? linkName : undefined}
                        onClick={menu.onItemClick(action.to)}
                    >
                        {mainContent}
                    </Link>
                ) : (
                    <button
                        {...{ [MENU_CONTROL_ATTRIBUTE]: "main" }}
                        type="button"
                        className={mainClassName}
                        aria-expanded={open}
                        aria-controls={submenuId}
                        aria-label={`${capitalize(noun)} menu`}
                        title={collapsed ? label : undefined}
                        onClick={(event: ReactMouseEvent<HTMLButtonElement>) => menu.toggleFrom(event.currentTarget)}
                    >
                        {mainContent}
                    </button>
                )}
                <button
                    {...{ [MENU_CONTROL_ATTRIBUTE]: "disclosure" }}
                    type="button"
                    className="portal-sidebar__link portal-sidebar__link--icon-only"
                    aria-expanded={open}
                    aria-controls={submenuId}
                    aria-label={`Show ${noun} menu`}
                    onClick={(event: ReactMouseEvent<HTMLButtonElement>) => menu.toggleFrom(event.currentTarget)}
                >
                    <ChevronDown className={chevronClassName} aria-hidden="true" />
                </button>
            </div>

            <ul id={submenuId} ref={submenuRef} className="portal-sidebar__submenu" hidden={!open}>
                {children(menu)}
            </ul>
        </li>
    )
}

function capitalize(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1)
}
