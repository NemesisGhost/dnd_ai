import type { ReactNode } from "react"

export interface FactGridItem {
    key: string
    label: string
    value: ReactNode
}

interface FactGridProps {
    items: FactGridItem[]
    className?: string
}

export function FactGrid({ items, className }: FactGridProps) {
    const gridClassName = className
        ? `fact-grid ${className}`
        : "fact-grid"

    return (
        <dl className={gridClassName}>
            {items.map((item) => (
                <div className="fact-grid__row" key={item.key}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                </div>
            ))}
        </dl>
    )
}
