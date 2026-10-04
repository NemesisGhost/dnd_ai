import type { ReactNode } from "react"
import { HierarchyContextPanel } from "./HierarchyContextPanel"
import type { CampaignContext } from "../types/bootstrap"

interface WorkspaceFrameProps {
  campaign: CampaignContext | null
  selectedCharacterId: string | null
  onSelectCharacter: (characterId: string | null) => void
  children: ReactNode
}

// The one <main> of a World or Campaign workspace page: the hierarchy context
// panel first in the DOM (so keyboard and screen-reader users reach the
// context before the content it scopes), then the routed page. Pages rendered
// inside it add no <main> of their own.
export function WorkspaceFrame({
  campaign,
  selectedCharacterId,
  onSelectCharacter,
  children,
}: WorkspaceFrameProps) {
  return (
    <main className="app-main campaign-workspace">
      <HierarchyContextPanel
        campaign={campaign}
        selectedCharacterId={selectedCharacterId}
        onSelectCharacter={onSelectCharacter}
      />

      <div className="campaign-workspace__content">{children}</div>
    </main>
  )
}
