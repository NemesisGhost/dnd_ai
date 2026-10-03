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
export function useAuthenticatedSession(): AuthenticatedOutletContext {
    return useOutletContext<AuthenticatedOutletContext>()
}
