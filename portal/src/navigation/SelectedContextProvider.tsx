import { useState } from "react"
import type { ReactNode } from "react"
import { SelectedContextStoreContext, createSelectedContextStore } from "./selectedContextStore"

// Owns the tab's selected-context store above the campaign-scoped session (main.tsx), so a change of
// campaign scope, which remounts the session provider, does not lose or reset what was selected.
export function SelectedContextProvider({ children }: { children: ReactNode }) {
    const [store] = useState(createSelectedContextStore)
    return <SelectedContextStoreContext.Provider value={store}>{children}</SelectedContextStoreContext.Provider>
}
