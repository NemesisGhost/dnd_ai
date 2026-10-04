import { useOutletContext } from "react-router"
import type { SessionBootstrap } from "../types/bootstrap"

export interface AuthenticatedOutletContext {
    bootstrap: SessionBootstrap
    reload: () => void
}

// Typed accessor for the context supplied by AuthenticatedAppLayout's
// <Outlet>. Any route nested under the global authenticated shell
// (global routes and every campaign route) reads the current bootstrap
// this way instead of each owning its own session boundary. Kept in its
// own module (rather than inside AuthenticatedAppLayout.tsx) so that
// file exports only a component, per react-refresh/only-export-components.
//
// The context exists only below an <Outlet context> that supplies it. A layout
// that nests routes must forward it (see WorldWorkspaceLayout); calling this
// anywhere else is a composition defect, reported here deliberately.
export function useAuthenticatedSession(): AuthenticatedOutletContext {
    const context = useOutletContext<AuthenticatedOutletContext | null | undefined>()

    if (context === undefined || context === null) {
        throw new Error(
            "useAuthenticatedSession must be used in a route rendered through " +
                "AuthenticatedAppLayout's <Outlet context>; a nested layout must " +
                "forward that context.",
        )
    }

    return context
}
