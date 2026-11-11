import { createContext, useContext, useEffect, useSyncExternalStore } from "react"
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
    // The authority generation under which the read that produced `name` (or the denial) STARTED: the
    // `authority` of `useAuthoringResource`. Null where the read began outside any registry.
    authority: LabelRegistry | null
}

/**
 * Publishes a record's name for breadcrumbs, from the read that has just answered.
 *
 * Ownership runs from the start of the request to the label: the read layer captures the registry that
 * is current when a request STARTS (see useAuthoringResource) and hands it back with the answer. The
 * label is published into that registry and no other. If the authority has changed since, that registry
 * is closed and the write is ignored; if it has not, the registry is the current one. A page that stays
 * mounted therefore publishes the answers of reads it starts under the new authority, and never the
 * answers of reads started under an earlier one, including an earlier generation of an authority that
 * has since returned to an equal value (each generation is its own registry). Nothing is registered
 * from a name the page merely still holds. There is no cleanup that deletes a label: an older
 * registration going away cannot remove a newer one; only an answer that denies the record, from a read
 * of the same generation, drops its label.
 */
export function useBreadcrumbLabel({ route, params, name, denied = false, authority }: BreadcrumbLabelEntry): void {
    const key = labelKey(route, params)
    useEffect(() => {
        if (authority === null) return
        if (denied) {
            authority.forget(key)
            return
        }
        if (name !== null && name !== undefined) authority.register(key, name)
    }, [authority, key, name, denied])
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
