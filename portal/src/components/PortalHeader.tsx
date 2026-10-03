import { Link } from "react-router"
import { Menu, X } from "lucide-react"
import { useSession } from "../context/SessionContext"
import type { RefObject } from "react"
import type { NavigationDrawerControl } from "../hooks/useNavigationDrawer"
import { ThemeSelector } from "../themes/ThemeSelector"
import { GlobalNavigation } from "./GlobalNavigation"
import { MAIN_NAVIGATION_ID } from "./PortalSidebar"
import { ProfileMenu } from "./ProfileMenu"

interface PortalHeaderProps {
  // "always": the authenticated global shell, where Home/Campaigns are
  // always relevant. "when-authenticated": public/boundary pages, where
  // an authenticated visitor (e.g. on an accept-invitation or not-found
  // page) still sees Home and Campaigns, but a signed-out visitor does
  // not.
  navigation: "always" | "when-authenticated"
  // Present only inside the authenticated shell: the narrow-viewport
  // drawer toggle for the persistent sidebar. Always rendered there (CSS
  // shows it only at narrow widths) so its focus-return target exists.
  drawer?: NavigationDrawerControl
  drawerToggleRef?: RefObject<HTMLButtonElement | null>
}

// Shared header chrome for both PublicLayout and AuthenticatedAppLayout
// (UI_DESIGN §4). Not an h1: each route supplies its own single
// page-level heading (docs/PLAN.md accessibility exit criterion) — this
// is persistent site-identity chrome, not a heading in the document
// outline.
export function PortalHeader({
  navigation,
  drawer,
  drawerToggleRef,
}: PortalHeaderProps) {
  const { state } = useSession()
  const isAuthenticated = state.status === "authenticated"
  const showGlobalNavigation = navigation === "always" || isAuthenticated

  return (
    <header className="app-header">
      {drawer !== undefined && (
        <button
          ref={drawerToggleRef}
          type="button"
          className="app-header__drawer-toggle"
          aria-controls={MAIN_NAVIGATION_ID}
          aria-expanded={drawer.open}
          aria-label={drawer.open ? "Close navigation" : "Open navigation"}
          onClick={drawer.toggle}
        >
          {drawer.open ? (
            <X aria-hidden="true" />
          ) : (
            <Menu aria-hidden="true" />
          )}
        </button>
      )}

      {isAuthenticated ? (
        <Link to="/home" className="app-header__title">
          D&amp;D AI Portal
        </Link>
      ) : (
        <p className="app-header__title">D&amp;D AI Portal</p>
      )}

      {showGlobalNavigation && <GlobalNavigation />}

      <ThemeSelector />
      <ProfileMenu />
    </header>
  )
}
