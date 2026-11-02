import type { ReactNode } from "react"

// Local horizontal scrolling for a wide table, so the table never widens the page. The region is
// named (by the same text as the table's caption) and focusable so keyboard users can scroll it.
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="table-scroll" role="region" aria-label={label} tabIndex={0}>
            {children}
        </div>
    )
}
