import { BookOpen } from "lucide-react"
import { useLocation } from "react-router"
import { ExpandableNavGroup } from "./ExpandableNavGroup"

interface KnowledgeNavGroupProps {
  campaignPath: string
  collapsed: boolean
  onNavigate: () => void
}

// Knowledge as a parent disclosure over "Claims" (the normal collection and the
// guided claim workspace) and "Member preview" (the read-only preview of what a
// selected member sees). Shown only where the person can preview a member
// (`access.manage`, the capability the server checks); everyone else keeps the
// plain Knowledge link, because there is nothing to expand.
export function KnowledgeNavGroup({
  campaignPath,
  collapsed,
  onNavigate,
}: KnowledgeNavGroupProps) {
  const { pathname } = useLocation()
  const base = `${campaignPath}/knowledge`
  const preview = `${base}/member-preview`
  const inPreview = pathname === preview || pathname.startsWith(`${preview}/`)
  const inKnowledge = pathname === base || pathname.startsWith(`${base}/`)

  return (
    <ExpandableNavGroup
      icon={BookOpen}
      label="Knowledge"
      sectionActive={inKnowledge}
      collapsed={collapsed}
      onNavigate={onNavigate}
      items={[
        { to: base, label: "Claims", isActive: () => inKnowledge && !inPreview },
        { to: preview, label: "Member preview", isActive: () => inPreview },
      ]}
    />
  )
}
