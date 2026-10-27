import { Link, useParams } from "react-router"
import { worldPath } from "../api/worlds"
import { ActionUnavailableNotice, ReadTerminal } from "../components/authoring/ReadState"
import { AccessDeniedContent } from "../components/TerminalState"
import { HOME_RECOVERY } from "../components/terminalRecovery"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { CreateWorldPage } from "../pages/CreateWorldPage"
import { EditWorldPage } from "../pages/EditWorldPage"
import type { WorldDetail } from "../types/worldAuthoring"
import { blockedReasonFor } from "../utils/blockedReason"
import { canCreateWorlds } from "../utils/worldAccess"
import { useAuthenticatedSession } from "./useAuthenticatedSession"
import type { ReactNode } from "react"
import "../components/authoring/authoring.css"

// Route-level guards for the world creation and editing pages, comparable to
// App.tsx's PlatformAccountsRoute. Without the server-computed authorization the
// page — its requests and form state — never mounts, and the person is told why
// (docs/UI_DESIGN.md, "Unavailable and unauthorized destinations"). They decide
// presentation only: POST /worlds and POST /worlds/{id}/update authorize
// independently on the server, which remains the enforcement boundary.

export function CreateWorldRoute() {
  const { bootstrap } = useAuthenticatedSession()

  // The route adapter is the gate, as for /platform/accounts: without the
  // server-computed `world.create`, CreateWorldPage never mounts, so no
  // GET /rulesets is sent and no form state exists. /worlds/new is a known
  // page, so the person is told their account cannot create worlds.
  // POST /worlds re-checks on the server.
  if (!canCreateWorlds(bootstrap)) {
    return (
      <AccessDeniedContent
        what="world creation"
        recovery={[{ to: "/worlds", label: "Go to Worlds" }, HOME_RECOVERY]}
      />
    )
  }

  return <CreateWorldPage />
}

// The page structure around every state of the edit route that is not the form: the same
// heading and breadcrumb the form page has, so the route is never a bare line of text. Focus
// moves to the heading once, when the read settles.
function EditWorldShell({
  settled,
  heading = "Edit world",
  children,
}: {
  settled: boolean
  heading?: string
  children: ReactNode
}) {
  const headingRef = usePageArrival(settled)
  return (
    <div className="world-page">
      <div className="authoring-page">
        <p className="authoring-page__breadcrumb">
          <Link to="/worlds">Worlds</Link>
        </p>
        <h1 ref={headingRef} tabIndex={-1}>
          {heading}
        </h1>
        {children}
      </div>
    </div>
  )
}

export function EditWorldRoute() {
  const { worldId = "" } = useParams()
  // Only the world read model is fetched — the same non-disclosing GET a
  // viewer of the overview makes. The edit form mounts only once the server's
  // `available_actions` contains `update`. A world that is missing or hidden
  // (404) reads identically; a world the person may read but not edit says
  // whether their role or the world's state is the reason.
  const { state, refetch } = useAuthoringResource<WorldDetail>(worldPath(worldId))

  if (state.kind === "loading") {
    return (
      <EditWorldShell settled={false}>
        <p role="status">Loading…</p>
      </EditWorldShell>
    )
  }
  if (state.kind !== "ready") {
    return (
      <EditWorldShell
        settled
        heading={
          state.kind === "error"
            ? "World could not be loaded"
            : state.kind === "denied"
              ? "Access denied"
              : "World not available"
        }
      >
        <ReadTerminal
          states={[state]}
          what="world"
          onRetry={refetch}
          back={{ to: "/worlds", label: "Back to Worlds" }}
        />
      </EditWorldShell>
    )
  }
  if (!state.data.available_actions.includes("update")) {
    const reason = blockedReasonFor(state.data.blocked_actions, "update")
    return (
      <EditWorldShell settled heading="Editing unavailable">
        <ActionUnavailableNotice
          noun="world"
          action="edit"
          reason={reason}
          archived={state.data.lifecycle_status === "archived"}
          back={{ to: `/worlds/${encodeURIComponent(state.data.world_id)}`, label: `Back to ${state.data.name}` }}
        />
      </EditWorldShell>
    )
  }

  return (
    <EditWorldPage
      world={state.data}
      refreshing={state.refreshing}
      refetch={refetch}
    />
  )
}
