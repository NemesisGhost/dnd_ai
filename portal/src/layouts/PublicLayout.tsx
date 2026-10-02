import { Outlet } from "react-router"
import { PortalHeader } from "../components/PortalHeader"
import { PortalFooter } from "../components/PortalFooter"

// Public and self-managed routes (login, invitation acceptance, account
// activation, password reset, not-found) keep identity chrome and the
// theme selector without exposing the global authenticated shell to a
// signed-out visitor. An authenticated visitor who lands on one of these
// routes still sees Home, Campaigns, and the profile menu (UI_DESIGN §4).
export function PublicLayout() {
  return (
    <>
      <PortalHeader navigation="when-authenticated" />
      <Outlet />
      <PortalFooter />
    </>
  )
}
