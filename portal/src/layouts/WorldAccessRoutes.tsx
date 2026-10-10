import { useParams } from "react-router"
import { worldPath } from "../api/worlds"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { CreateWorldPage } from "../pages/CreateWorldPage"
import { EditWorldPage } from "../pages/EditWorldPage"
import { NotFoundContent } from "../pages/NotFoundPage"
import type { WorldDetail } from "../types/worldAuthoring"
import { canCreateWorlds } from "../utils/worldAccess"
import { useAuthenticatedSession } from "./useAuthenticatedSession"

// Route-level guards for the world creation and editing pages, comparable to
// App.tsx's PlatformAccountsRoute. Without the server-computed authorization a
// manually entered URL renders the ordinary not-found content and the page —
// its requests and form state — never mounts. They decide presentation only:
// POST /worlds and POST /worlds/{id}/update authorize independently on the
// server, which remains the enforcement boundary.

export function CreateWorldRoute() {
  const { bootstrap } = useAuthenticatedSession()

  // The route adapter is the gate, as for /platform/accounts: without the
  // server-computed `world.create`, CreateWorldPage never mounts, so no
  // GET /rulesets is sent and no form state exists. A manually entered URL
  // gets the ordinary not-found page. POST /worlds re-checks on the server.
  if (!canCreateWorlds(bootstrap)) {
    return <NotFoundContent />
  }

  return <CreateWorldPage />
}

export function EditWorldRoute() {
  const { worldId = "" } = useParams()
  // Only the world read model is fetched — the same non-disclosing GET a
  // viewer of the overview makes. The edit form mounts only once the server's
  // `available_actions` contains `update`; otherwise (no access, unknown
  // world, view-only, or not editable right now) the route is not found.
  const { state, refetch } = useAuthoringResource<WorldDetail>(worldPath(worldId))

  if (state.kind === "loading") {
    return (
      <p role="status" className="authoring-page">
        Loading…
      </p>
    )
  }
  if (state.kind === "error") {
    return (
      <p role="alert" className="authoring-page">
        This page could not be loaded. Try reloading the page.
      </p>
    )
  }
  if (state.kind !== "ready" || !state.data.available_actions.includes("update")) {
    return <NotFoundContent />
  }

  return (
    <EditWorldPage
      world={state.data}
      refreshing={state.refreshing}
      refetch={refetch}
    />
  )
}
