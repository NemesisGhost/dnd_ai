import { CampaignLayout } from "./CampaignLayout"
import { useAuthenticatedSession } from "./useAuthenticatedSession"

// Campaign-specific context: reads the already-authenticated bootstrap
// from AuthenticatedAppLayout's outlet context and renders CampaignLayout.
// It no longer wraps AuthenticatedSessionBoundary itself — that gate now
// lives once, in AuthenticatedAppLayout (UI_DESIGN §4).
export function CampaignSessionBoundary() {
  const { bootstrap } = useAuthenticatedSession()

  return <CampaignLayout bootstrap={bootstrap} />
}
