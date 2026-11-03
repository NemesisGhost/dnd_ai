import { useMemo } from "react"
import type { ReactNode } from "react"
import { useSession } from "../context/SessionContext"
import { BreadcrumbLabelContext, LabelRegistry, useLabelRegistryLifecycle } from "./BreadcrumbLabelContext"
import { authorityFingerprint } from "./labelAuthority"

// Mounted by the campaign workspace, inside SessionProvider, so the campaign-scope remount drops the
// registry with everything else. A new registry is made whenever the authority fingerprint changes
// (bootstrap authority, available perspectives, clock-set state, committed perspective) and the
// previous one is closed. No authenticated session, or a campaign the session does not list, means no
// registry at all and so only generic labels. Invalidation never navigates and never moves focus.
export function BreadcrumbLabelProvider({
    campaignId,
    characterId,
    children,
}: {
    campaignId: string | null
    characterId: string | null
    children: ReactNode
}) {
    const { state } = useSession()
    const fingerprint = authorityFingerprint(
        state.status === "authenticated" ? state.bootstrap : null,
        campaignId,
        characterId,
    )
    // A new registry per fingerprint value (the fingerprint is the memo key). Returning to an earlier value makes another new registry,
    // so a registrant from before the change cannot write into it.
    const registry = useMemo(() => (fingerprint === null ? null : new LabelRegistry()), [fingerprint])
    useLabelRegistryLifecycle(registry)
    return <BreadcrumbLabelContext.Provider value={registry}>{children}</BreadcrumbLabelContext.Provider>
}
