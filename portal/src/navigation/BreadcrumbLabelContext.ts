import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react"
import { LabelRegistry, labelKey } from "./labelRegistry"
import type { LabelParams } from "./labelRegistry"

// The registry in force for the current authority, or null where there is none (outside a campaign
// workspace, or without an authenticated session). Everything below degrades to generic labels then.
export const BreadcrumbLabelContext = createContext<LabelRegistry | null>(null)

const NO_SUBSCRIPTION = (): (() => void) => () => undefined
const NO_VERSION = (): number => 0

export interface BreadcrumbLabelEntry {
    route: string
    params: LabelParams
    // The record's name exactly as the page's own authorized read returned it; null while unread.
    name: string | null | undefined
    // The page's read of this record was refused or the record is unavailable (403/404): the label is
    // dropped and not registered.
    denied?: boolean
}

/**
 * Registers a record's name for breadcrumbs, from the page that has just read it.
 *
 * The page must pass only a name it rendered from its own authorized read; this adds no request. The
 * registrant is bound to the registry that was current when it mounted: after the authority changes
 * (see labelAuthority.ts) that registry is closed and this page's later writes are ignored, until the
 * page is opened again under the new authority.
 */
export function useBreadcrumbLabel({ route, params, name, denied = false }: BreadcrumbLabelEntry): void {
    const current = useContext(BreadcrumbLabelContext)
    const [owner] = useState(current)
    const key = labelKey(route, params)
    useEffect(() => {
        if (owner === null) return
        if (denied) {
            owner.forget(key)
            return
        }
        if (name !== null && name !== undefined) owner.register(key, name)
    }, [owner, key, name, denied])
}

/** Looks up registered names. A missing name is `undefined`, and the caller shows a generic noun. */
export function useBreadcrumbLabelReader(): (route: string, params: LabelParams) => string | undefined {
    const registry = useContext(BreadcrumbLabelContext)
    useSyncExternalStore(registry?.subscribe ?? NO_SUBSCRIPTION, registry?.getVersion ?? NO_VERSION)
    return (route, params) => registry?.labelFor(labelKey(route, params))
}

/** For the provider: a registry for one authority, closed when that authority is replaced. */
export function useLabelRegistryLifecycle(registry: LabelRegistry | null): void {
    useEffect(() => {
        if (registry === null) return undefined
        registry.activate()
        return () => registry.close()
    }, [registry])
}

export { LabelRegistry }
