import { useId, type ReactNode } from "react"

interface DetailPanelProps {
    title: string
    description?: ReactNode
    isEmpty?: boolean
    emptyState?: ReactNode
    className?: string
    children: ReactNode
}

export function DetailPanel({
    title,
    description,
    isEmpty = false,
    emptyState,
    className,
    children,
}: DetailPanelProps) {
    const headingId = useId()

    const panelClassName = className
        ? `detail-panel ${className}`
        : "detail-panel"

    return (
        <section
            className={panelClassName}
            aria-labelledby={headingId}
        >
            <h2 id={headingId} className="detail-panel__heading">
                {title}
            </h2>

            {description !== undefined && (
                <p className="detail-panel__description">
                    {description}
                </p>
            )}

            <div className="detail-panel__body">
                {isEmpty
                    ? (emptyState ?? (
                        <p className="detail-panel__empty">
                            Nothing recorded.
                        </p>
                    ))
                    : children}
            </div>
        </section>
    )
}
