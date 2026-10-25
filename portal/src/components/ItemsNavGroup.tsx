import { Package } from "lucide-react"
import { useLocation } from "react-router"
import { ExpandableNavGroup } from "./ExpandableNavGroup"
import { NEEDS_WORLD_ROLE } from "./navigationReasons"

interface ItemsNavGroupProps {
  campaignPath: string
  collapsed: boolean
  // Whether the caller may read the world's private authoring catalog (the definitions list holds
  // drafts); Inventory is the campaign's own and stays available.
  canOpenDefinitions: boolean
  onNavigate: () => void
}

const under = (pathname: string, base: string): boolean =>
  pathname === base || pathname.startsWith(`${base}/`)

// Items as a parent disclosure over "Inventory" (the world's item instances and the item
// workspace) and "Definitions" (the reusable kinds of item). Shown only where the person can edit
// canon (the capability the server checks). The selection follows the address alone: an item
// opened from the World page lies under the Worlds group, never here.
export function ItemsNavGroup({ campaignPath, collapsed, canOpenDefinitions, onNavigate }: ItemsNavGroupProps) {
  const { pathname } = useLocation()
  const inventory = `${campaignPath}/items`
  const definitions = `${campaignPath}/item-definitions`
  const inInventory = under(pathname, inventory)
  const inDefinitions = under(pathname, definitions)

  return (
    <ExpandableNavGroup
      icon={Package}
      label="Items"
      sectionActive={inInventory || inDefinitions}
      collapsed={collapsed}
      onNavigate={onNavigate}
      items={[
        { to: inventory, label: "Inventory", isActive: () => inInventory },
        {
          to: definitions,
          label: "Definitions",
          isActive: () => inDefinitions,
          unavailableReason: canOpenDefinitions ? undefined : NEEDS_WORLD_ROLE,
        },
      ]}
    />
  )
}
