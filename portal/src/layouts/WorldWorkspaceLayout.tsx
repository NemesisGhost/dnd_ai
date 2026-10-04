import { Outlet } from "react-router"
import { WorkspaceFrame } from "../components/WorkspaceFrame"
import { useAuthenticatedSession } from "./useAuthenticatedSession"
import type { AuthenticatedOutletContext } from "./useAuthenticatedSession"

const NO_PERSPECTIVE = () => undefined

// The persistent workspace for every /worlds route: the hierarchy context
// panel stays mounted while the routed World, Timelines, and Timeline pages
// change. There is no campaign here, so no character perspective exists. The
// shell's authenticated outlet context is forwarded to the routed page.
export function WorldWorkspaceLayout() {
  const session = useAuthenticatedSession()

  return (
    <WorkspaceFrame
      campaign={null}
      selectedCharacterId={null}
      onSelectCharacter={NO_PERSPECTIVE}
    >
      <Outlet context={session satisfies AuthenticatedOutletContext} />
    </WorkspaceFrame>
  )
}
