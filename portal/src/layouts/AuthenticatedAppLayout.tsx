import { Outlet } from "react-router"
import { AuthenticatedSessionBoundary } from "./AuthenticatedSessionBoundary"
import { PortalHeader } from "../components/PortalHeader"
import { PortalFooter } from "../components/PortalFooter"
import { PortalSidebar } from "../components/PortalSidebar"
import { useNavigationDrawer } from "../hooks/useNavigationDrawer"
import { WorkspaceHierarchyProvider } from "../context/WorkspaceHierarchyProvider"
import { AnnouncerProvider } from "../components/authoring/AnnouncerProvider"
import type { AuthenticatedOutletContext } from "./useAuthenticatedSession"

// The authenticated application shell and the single session gate for
// every authenticated route — global (Settings, Campaigns, Account,
// Platform Accounts, the /home landing resolver) and campaign routes
// (UI_DESIGN §4). The header and the one persistent sidebar render
// outside the boundary, so navigation stays mounted through the loading
// state that every campaign-scope change causes via RouteSessionProvider's
// scope-keyed remount, and disappears only when the session is actually
// unauthenticated (the sidebar renders nothing then).
//
// Pages render their own <main>, except World and Campaign workspace pages,
// whose <main> (with the hierarchy context panel) is WorkspaceFrame.
export function AuthenticatedAppLayout() {
  const { control: drawer, toggleRef } = useNavigationDrawer()

  return (
    <AnnouncerProvider>
    <WorkspaceHierarchyProvider>
    <div className="authenticated-shell">
      <PortalHeader drawer={drawer} drawerToggleRef={toggleRef} />

      <div className="authenticated-shell__body">
        <PortalSidebar drawer={drawer} />

        <div className="authenticated-shell__content">
          <AuthenticatedSessionBoundary>
            {(bootstrap, reload) => (
              <Outlet
                context={
                  { bootstrap, reload } satisfies AuthenticatedOutletContext
                }
              />
            )}
          </AuthenticatedSessionBoundary>
        </div>
      </div>

      <PortalFooter />
    </div>
    </WorkspaceHierarchyProvider>
    </AnnouncerProvider>
  )
}
