import type { ReactNode } from "react"
import { Navigate } from "react-router"
import { useSession } from "../context/SessionContext"
import type { SessionBootstrap } from "../types/bootstrap"
import PlaceholderPage from "../pages/PlaceholderPage"

interface AuthenticatedSessionBoundaryProps {
    children: (
        bootstrap: SessionBootstrap,
    ) => ReactNode
}

export function AuthenticatedSessionBoundary({
    children,
}: AuthenticatedSessionBoundaryProps) {
    const {
        state,
        reload,
    } = useSession()

    switch (state.status) {
        case "loading":
            return (
                <main className="app-main">
                    <PlaceholderPage
                        title="Loading portal"
                        description="Checking your session and authorized content."
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
                            Your session could not be checked. No
                            protected information has been displayed.
                        </p>

                        <button
                            type="button"
                            onClick={reload}
                        >
                            Try again
                        </button>
                    </section>
                </main>
            )

        case "authenticated":
            return children(state.bootstrap)
    }
}