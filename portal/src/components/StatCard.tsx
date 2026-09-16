import type { ReactNode } from "react"

interface StatCardProps {
    label: string
    value?: ReactNode
    secondary?: ReactNode
    className?: string
    children?: ReactNode
}

export function StatCard({
    label,
    value,
    secondary,
    className,
    children,
}: StatCardProps) {
    const cardClassName = className
        ? `stat-card ${className}`
        : "stat-card"

    return (
        <figure className={cardClassName}>
            <figcaption className="stat-card__label">
                {label}
            </figcaption>

            {value !== undefined && (
                <p className="stat-card__value">{value}</p>
            )}

            {children}

            {secondary !== undefined && (
                <p className="stat-card__secondary">{secondary}</p>
            )}
        </figure>
    )
}
