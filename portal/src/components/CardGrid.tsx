import type { ReactNode } from "react"

interface CardGridProps {
    ariaLabel: string
    className?: string
    children: ReactNode
}

// Responsive collection grid shared by every card-based collection (World,
// Knowledge, Quests, ...). Carries no domain knowledge: callers supply
// already-built <li> children (see EntityCard), typically produced by a
// domain-specific wrapper that selects which authorized fields to show.
export function CardGrid({ ariaLabel, className, children }: CardGridProps) {
    const gridClassName = className ? `card-grid ${className}` : "card-grid"

    return (
        <ul className={gridClassName} aria-label={ariaLabel}>
            {children}
        </ul>
    )
}
