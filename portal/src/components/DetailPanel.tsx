import { useId, type ReactNode } from "react"

interface DetailPanelProps {
    title: string
    description?: ReactNode
    isEmpty?: boolean
    emptyState?: ReactNode
    className?: string
    // Follows the page outline: 2 for a peer region of the page, 3 when nested under a section.
    headingLevel?: 2 | 3
    // For a host that needs to label or focus the heading by a stable id.
    headingId?: string
    // At most two compact controls that act on the whole panel (an Add toggle, an Edit link).
    headerActions?: ReactNode
    children: ReactNode
}

// A panel, or only its content when a staged section already supplies the surface and the heading.
export function PanelFrame({
    embedded = false,
    title,
    headingId,
    children,
}: {
    embedded?: boolean
    title: string
    headingId?: string
    children: ReactNode
}) {
    return embedded ? (
        <>{children}</>
    ) : (
        <DetailPanel title={title} headingId={headingId}>
            {children}
        </DetailPanel>
    )
}

export function DetailPanel({
    title,
    description,
    isEmpty = false,
    emptyState,
    className,
    headingLevel = 2,
    headingId,
    headerActions,
    children,
}: DetailPanelProps) {
    const generatedId = useId()
    const labelId = headingId ?? generatedId
    const Heading = headingLevel === 2 ? "h2" : "h3"

    const panelClassName = className
        ? `detail-panel ${className}`
        : "detail-panel"

    return (
        <section
            className={panelClassName}
            aria-labelledby={labelId}
        >
            <div className="detail-panel__header">
                <Heading id={labelId} className="detail-panel__heading">
                    {title}
                </Heading>
                {headerActions}
            </div>

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
