import { ShieldCheck } from "lucide-react"
import { useLocation } from "react-router"
import { ExpandableNavGroup } from "./ExpandableNavGroup"

interface AccessNavGroupProps {
  campaignPath: string
  collapsed: boolean
  onNavigate: () => void
}

// Access as a parent disclosure over "Access Management", "Invitations",
// and "Audit History". All children share the same `access.manage` gate, so
// the caller shows or hides the whole group.
export function AccessNavGroup({
  campaignPath,
  collapsed,
  onNavigate,
}: AccessNavGroupProps) {
  const { pathname } = useLocation()
  const accessBasePath = `${campaignPath}/access`
  const settingsPath = `${campaignPath}/settings`
  const active =
    pathname === accessBasePath ||
    pathname.startsWith(`${accessBasePath}/`) ||
    pathname === settingsPath

  return (
    <ExpandableNavGroup
      icon={ShieldCheck}
      label="Access"
      sectionActive={active}
      collapsed={collapsed}
      onNavigate={onNavigate}
      items={[
        { to: accessBasePath, label: "Access Management", end: true },
        { to: `${accessBasePath}/invitations`, label: "Invitations" },
        { to: `${accessBasePath}/audit`, label: "Audit History" },
        { to: settingsPath, label: "Campaign Settings" },
      ]}
    />
  )
}
