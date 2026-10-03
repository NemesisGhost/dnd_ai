import { Outlet } from "react-router"
import { AuthenticatedSessionBoundary } from "./AuthenticatedSessionBoundary"
import { PortalHeader } from "../components/PortalHeader"
import { PortalFooter } from "../components/PortalFooter"
import type { AuthenticatedOutletContext } from "./useAuthenticatedSession"

// The global authenticated shell and the single session gate for both
// global routes (Home, Campaigns, Account, Platform Accounts) and
// campaign routes (UI_DESIGN §4). The header renders outside the
// boundary so Home and Campaigns stay visible during the loading state
// that every campaign-scope change causes via RouteSessionProvider's
// scope-keyed remount (§9.2 of the navigation plan).
export function AuthenticatedAppLayout() {
  return (
    <>
      <PortalHeader navigation="always" />

      <AuthenticatedSessionBoundary>
        {(bootstrap, reload) => (
          <Outlet
            context={
              { bootstrap, reload } satisfies AuthenticatedOutletContext
            }
          />
        )}
      </AuthenticatedSessionBoundary>

      <PortalFooter />
    </>
  )
}
