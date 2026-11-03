// The breadcrumb label registry: names that pages rendered from their own authorized reads, held in
// tab memory only so an ancestor in a breadcrumb can show a name instead of a generic noun.
//
// One registry instance belongs to one authority (navigation/labelAuthority.ts). When the authority
// changes, the provider makes a NEW registry and closes the old one for good. Registrants capture the
// registry that was current when they mounted and only ever write to that one, so
//   - a late write from an earlier authority reaches a closed registry and is ignored, including after
//     the authority changes and then returns to its earlier value (the returned-to value is a new
//     registry, not the old one); and
//   - a closed registry holds nothing.
// Nothing here is persisted or put in router state: a label is never part of a task descriptor.

export const MAX_LABEL_LENGTH = 120

export type LabelParams = Readonly<Record<string, string>>

/** The registry key for a route and its id parameters. Order of parameters does not matter. */
export function labelKey(route: string, params: LabelParams): string {
    const parts = Object.keys(params)
        .sort()
        .map((name) => `${name}=${params[name]}`)
    return `${route}|${parts.join("&")}`
}

// A label is shown as text, so the only rules are: a non-empty string, no control characters, bounded.
function cleanLabel(value: unknown): string | null {
    if (typeof value !== "string") return null
    let out = ""
    for (const character of value) {
        const code = character.codePointAt(0) ?? 0
        out += code <= 0x1f || code === 0x7f ? " " : character
    }
    const text = out.replace(/\s+/g, " ").trim()
    if (text === "") return null
    return text.length > MAX_LABEL_LENGTH ? `${text.slice(0, MAX_LABEL_LENGTH - 1)}…` : text
}

export class LabelRegistry {
    private labels = new Map<string, string>()
    private accepting = true
    private version = 0
    private listeners = new Set<() => void>()

    private emit(): void {
        this.version += 1
        this.listeners.forEach((listener) => listener())
    }

    /** Accepts a label from a mounted registrant of this registry's authority. False when ignored. */
    register(key: string, name: unknown): boolean {
        if (!this.accepting) return false
        const label = cleanLabel(name)
        if (label === null) return false
        if (this.labels.get(key) === label) return true
        this.labels.set(key, label)
        this.emit()
        return true
    }

    /** The registrant was told the record is denied or unavailable: drop its label. */
    forget(key: string): void {
        if (this.labels.delete(key)) this.emit()
    }

    labelFor(key: string): string | undefined {
        return this.labels.get(key)
    }

    // Called when the authority is replaced or the provider goes away. Idempotent.
    close(): void {
        this.accepting = false
        if (this.labels.size > 0) {
            this.labels.clear()
            this.emit()
        }
    }

    // React StrictMode runs an effect's cleanup and setup once on mount; a registry that is still the
    // current one must accept writes again afterwards. A registry that was superseded is never set up
    // again, so it stays closed.
    activate(): void {
        this.accepting = true
    }

    get open(): boolean {
        return this.accepting
    }

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => {
            this.listeners.delete(listener)
        }
    }

    getVersion = (): number => this.version
}
