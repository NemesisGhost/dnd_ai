import { Navigate } from "react-router"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import { resolveLandingPath } from "../utils/landingDestination"

// The /home route: an authenticated landing resolver with no content of its
// own (docs/UI_DESIGN.md §4.2). /home stays a stable URL for bookmarks, the
// portal brand link, and the post-login default. It always replaces itself
// in history, so Back from the landing page leaves the app rather than
// bouncing through /home, and it can never loop: the targets are
// /campaigns and /app/:id/home, neither of which redirects back here.
export function LandingRedirect() {
    const { bootstrap } = useAuthenticatedSession()

    return <Navigate to={resolveLandingPath(bootstrap)} replace />
}
