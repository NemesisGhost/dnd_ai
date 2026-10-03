import { Outlet } from "react-router"
import { PortalHeader } from "../components/PortalHeader"
import { PortalFooter } from "../components/PortalFooter"

// Public and self-managed routes (login, invitation acceptance, account
// activation, password reset, not-found) keep identity chrome without the
// authenticated shell: no sidebar and no navigation, even for an
// authenticated visitor, who still gets the profile menu in the header
// (UI_DESIGN §4).
export function PublicLayout() {
  return (
    <>
      <PortalHeader />
      <Outlet />
      <PortalFooter />
    </>
  )
}
