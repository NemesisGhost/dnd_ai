import { Navigate } from "react-router"
import { useSession } from "../context/SessionContext"
import PlaceholderPage from "../pages/PlaceholderPage"
import { CampaignLayout } from "./CampaignLayout"

export function CampaignSessionBoundary() {
  const { state, reload } = useSession()

  switch (state.status) {
    case "loading":
      return (
        <main className="app-main">
          <PlaceholderPage
            title="Loading portal"
            description="Checking your session and authorized campaigns."
          />
        </main>
      )

    case "unauthenticated":
      return <Navigate to="/login" replace />

    case "error":
      return (
        <main className="app-main">
          <section
            className="placeholder-page"
            aria-labelledby="session-error-heading"
          >
            <h1 id="session-error-heading">
              Portal unavailable
            </h1>
            <p>
              Your session could not be checked. No campaign
              information has been displayed.
            </p>
            <button type="button" onClick={reload}>
              Try again
            </button>
          </section>
        </main>
      )

    case "authenticated":
      return (
        <CampaignLayout bootstrap={state.bootstrap} />
      )
  }
}