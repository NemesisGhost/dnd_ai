import { useId } from "react"
import type { LucideIcon } from "lucide-react"

interface DisabledNavItemProps {
  label: string
  // A neutral prerequisite or status ("Select a campaign first"). Must never
  // carry a name, ID, capability, or count of anything the caller may not see.
  reason: string
  collapsed: boolean
  // Top-level entries show an icon and use the link styling; nested entries
  // use the sublink styling and have no icon.
  icon?: LucideIcon
}

// The established disabled-navigation pattern (the Ask entry): a non-link,
// non-focusable element with the normal icon and label, `aria-disabled`, and
// the prerequisite exposed as its accessible description. It keeps the slot an
// enabled entry would occupy so the sidebar does not change shape with route
// context. Never rendered as an anchor and never carries `aria-current`.
export function DisabledNavItem({
  label,
  reason,
  collapsed,
  icon: Icon,
}: DisabledNavItemProps) {
  const reasonId = useId()

  return (
    <>
      <span
        className={
          Icon === undefined
            ? "portal-sidebar__sublink portal-sidebar__sublink--disabled"
            : "portal-sidebar__link portal-sidebar__link--disabled"
        }
        aria-disabled="true"
        aria-describedby={reasonId}
        title={collapsed ? `${label}: ${reason}` : reason}
      >
        {Icon !== undefined && (
          <Icon className="portal-sidebar__icon" aria-hidden="true" />
        )}
        <span className="portal-sidebar__label">{label}</span>
      </span>
      <span id={reasonId} className="portal-sidebar__reason">
        {reason}
      </span>
    </>
  )
}
