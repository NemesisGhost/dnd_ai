import { Link } from "react-router"
import { useSession } from "../context/SessionContext"
import { ThemeSelector } from "../themes/ThemeSelector"
import { GlobalNavigation } from "./GlobalNavigation"
import { ProfileMenu } from "./ProfileMenu"

interface PortalHeaderProps {
  // "always": the authenticated global shell, where Home/Campaigns are
  // always relevant. "when-authenticated": public/boundary pages, where
  // an authenticated visitor (e.g. on an accept-invitation or not-found
  // page) still sees Home and Campaigns, but a signed-out visitor does
  // not.
  navigation: "always" | "when-authenticated"
}

// Shared header chrome for both PublicLayout and AuthenticatedAppLayout
// (UI_DESIGN §4). Not an h1: each route supplies its own single
// page-level heading (docs/PLAN.md accessibility exit criterion) — this
// is persistent site-identity chrome, not a heading in the document
// outline.
export function PortalHeader({ navigation }: PortalHeaderProps) {
  const { state } = useSession()
  const isAuthenticated = state.status === "authenticated"
  const showGlobalNavigation = navigation === "always" || isAuthenticated

  return (
    <header className="app-header">
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
