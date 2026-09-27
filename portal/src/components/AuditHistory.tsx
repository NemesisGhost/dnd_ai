import { useId, useState } from "react"
import "./AuditHistory.css"
import { useAuditHistory } from "../hooks/useAuditHistory"
import type {
    AuditHistoryCategory,
    AuditHistoryFilters,
    AuditHistoryItem,
} from "../types/auditHistory"
import {
    AUDIT_HISTORY_CATEGORIES,
    EMPTY_AUDIT_HISTORY_FILTERS,
} from "../types/auditHistory"

export interface AuditActorOption {
    user_id: string
    display_name: string
}

export interface AuditHistoryProps {
    /**
     * The campaign whose audit history this instance shows. Changing this
     * prop always resets to a fresh load for the new campaign — the
     * underlying hook (`useAuditHistory`) never shows a previous
     * campaign's rows, even briefly, while the new request is in flight.
     *
     * Rendered by `CampaignAccessAuditPage.tsx` at its own
     * `/app/:campaignId/access/audit` route — this component owns that
     * route's single page-level `<h1>`.
     */
    campaignId: string
    /**
     * The actor filter's own option list (checkpoint 14; re-sourced by
     * the audit-actor-contract fix). Originally sourced from the caller's
     * `GET .../access-overview` `members` array; now sourced from the
     * bounded, identically `access.manage`-authorized `GET .../audit-
     * history/actors` facet instead (`useAuditActors`), so opening this
     * route no longer needs the complete access-overview response
     * (memberships, roles, relationships, grants, access groups) merely
     * to populate this one filter. Either way, never a new account-
     * directory query of this component's own. Defaults to `[]` — the
     * actor filter is simply not offered when the caller has no actor
     * list in hand yet (loading, unavailable, or errored).
     */
    actors?: AuditActorOption[]
}

const CATEGORY_LABELS: Record<AuditHistoryCategory, string> = {
    membership: "Membership",
    role: "Role",
    character_relationship: "Character relationship",
    resource_grant: "Access grant",
    invitation: "Invitation",
    campaign: "Campaign",
    access_group: "Access group",
    access_group_membership: "Access group membership",
}

function formatOccurredAt(iso: string): string {
    const parsed = new Date(iso)
    if (Number.isNaN(parsed.getTime())) {
        // The server always sends a valid ISO-8601 timestamp; this is a
        // safe fallback for an unexpected value rather than showing
        // nothing or throwing.
        return iso
    }
    return parsed.toLocaleString()
}

interface PendingFilters {
    category: AuditHistoryCategory | ""
    actorUserId: string
    occurredFrom: string
    occurredTo: string
}

const emptyPendingFilters: PendingFilters = {
    category: "",
    actorUserId: "",
    occurredFrom: "",
    occurredTo: "",
}

function toIsoOrNull(dateValue: string): string | null {
    if (dateValue === "") {
        return null
    }
    const parsed = new Date(dateValue)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

function AuditHistoryRow({ item }: { item: AuditHistoryItem }) {
    return (
        <tr>
            <td>{formatOccurredAt(item.occurred_at)}</td>
            <td>{CATEGORY_LABELS[item.category]}</td>
            <td>{item.action_label}</td>
            <td>
                {item.actor_label}
                {item.actor_type === "service" && (
                    <span className="audit-history__actor-type">
                        {" "}
                        (service)
                    </span>
                )}
            </td>
            <td>{item.target_label ?? "—"}</td>
            <td>{item.change_summary ?? "—"}</td>
        </tr>
    )
}

export function AuditHistory({ campaignId, actors = [] }: AuditHistoryProps) {
    const headingId = useId()
    const categoryId = useId()
    const actorId = useId()
    const fromId = useId()
    const toId = useId()

    const [pending, setPending] = useState<PendingFilters>(
        emptyPendingFilters,
    )
    const [appliedFilters, setAppliedFilters] =
        useState<AuditHistoryFilters>(
            EMPTY_AUDIT_HISTORY_FILTERS,
        )

    const { state, retry, loadMore } = useAuditHistory(
        campaignId,
        appliedFilters,
    )

    function applyFilters() {
        setAppliedFilters({
            ...EMPTY_AUDIT_HISTORY_FILTERS,
            category:
                pending.category === ""
                    ? null
                    : pending.category,
            actorUserId:
                pending.actorUserId === ""
                    ? null
                    : pending.actorUserId,
            occurredFrom: toIsoOrNull(
                pending.occurredFrom,
            ),
            occurredTo: toIsoOrNull(pending.occurredTo),
        })
    }

    function clearFilters() {
        setPending(emptyPendingFilters)
        setAppliedFilters(EMPTY_AUDIT_HISTORY_FILTERS)
    }

    const filtersForm = (
        <form
            className="audit-history__filters"
            onSubmit={(event) => {
                event.preventDefault()
                applyFilters()
            }}
        >
            <div className="audit-history__filter-field">
                <label htmlFor={categoryId}>
                    Category
                </label>
                <select
                    id={categoryId}
                    value={pending.category}
                    onChange={(event) => {
                        const value = event.target
                            .value as
                            | AuditHistoryCategory
                            | ""
                        setPending((current) => ({
                            ...current,
                            category: value,
                        }))
                    }}
                >
                    <option value="">
                        All categories
                    </option>
                    {AUDIT_HISTORY_CATEGORIES.map(
                        (category) => (
                            <option
                                key={category}
                                value={category}
                            >
                                {
                                    CATEGORY_LABELS[
                                        category
                                    ]
                                }
                            </option>
                        ),
                    )}
                </select>
            </div>

            {actors.length > 0 && (
                <div className="audit-history__filter-field">
                    <label htmlFor={actorId}>Actor</label>
                    <select
                        id={actorId}
                        value={pending.actorUserId}
                        onChange={(event) => {
                            const value = event.target.value
                            setPending((current) => ({
                                ...current,
                                actorUserId: value,
                            }))
                        }}
                    >
                        <option value="">All actors</option>
                        {actors.map((actor) => (
                            <option key={actor.user_id} value={actor.user_id}>
                                {actor.display_name}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            <div className="audit-history__filter-field">
                <label htmlFor={fromId}>From</label>
                <input
                    id={fromId}
                    type="date"
                    value={pending.occurredFrom}
                    onChange={(event) => {
                        const value = event.target.value
                        setPending((current) => ({
                            ...current,
                            occurredFrom: value,
                        }))
                    }}
                />
            </div>

            <div className="audit-history__filter-field">
                <label htmlFor={toId}>To</label>
                <input
                    id={toId}
                    type="date"
                    value={pending.occurredTo}
                    onChange={(event) => {
                        const value = event.target.value
                        setPending((current) => ({
                            ...current,
                            occurredTo: value,
                        }))
                    }}
                />
            </div>

            <button type="submit">Apply filters</button>
            <button type="button" onClick={clearFilters}>
                Clear filters
            </button>
        </form>
    )

    return (
        <section aria-labelledby={headingId}>
            <h1 id={headingId}>Audit history</h1>

            {filtersForm}

            {state.status === "loading" && (
                <div
                    role="region"
                    aria-label="Audit history results"
                    aria-busy="true"
                >
                    <p role="status">
                        Loading audit history…
                    </p>
                </div>
            )}

            {state.status === "unavailable" && (
                <div
                    role="region"
                    aria-label="Audit history results"
                >
                    <p role="status">
                        Audit history is not available for
                        this campaign.
                    </p>
                </div>
            )}

            {state.status === "error" && (
                <div
                    role="region"
                    aria-label="Audit history results"
                >
                    <p role="status">
                        The portal could not load audit
                        history. Try again.
                    </p>
                    <button type="button" onClick={retry}>
                        Try again
                    </button>
                </div>
            )}

            {state.status === "success" &&
                state.items.length === 0 && (
                    <div
                        role="region"
                        aria-label="Audit history results"
                    >
                        <p role="status">
                            No audit history matches the
                            current filters.
                        </p>
                    </div>
                )}

            {state.status === "success" &&
                state.items.length > 0 && (
                    <div
                        role="region"
                        aria-label="Audit history results"
                        className="audit-history__table-wrapper"
                    >
                        <p role="status">
                            Showing {state.items.length}{" "}
                            audit history{" "}
                            {state.items.length === 1
                                ? "entry"
                                : "entries"}
                            .
                        </p>

                        <table className="audit-history__table">
                            <caption>
                                Campaign audit history
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col">
                                        Occurred at
                                    </th>
                                    <th scope="col">
                                        Category
                                    </th>
                                    <th scope="col">
                                        Action
                                    </th>
                                    <th scope="col">
                                        Actor
                                    </th>
                                    <th scope="col">
                                        Target
                                    </th>
                                    <th scope="col">
                                        Details
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {state.items.map(
                                    (item) => (
                                        <AuditHistoryRow
                                            key={
                                                item.change_log_id
                                            }
                                            item={item}
                                        />
                                    ),
                                )}
                            </tbody>
                        </table>

                        {state.nextCursor !== null && (
                            <button
                                type="button"
                                onClick={loadMore}
                                disabled={
                                    state.isLoadingMore
                                }
                            >
                                {state.isLoadingMore
                                    ? "Loading more…"
                                    : "Load more"}
                            </button>
                        )}

                        {state.loadMoreError && (
                            <p role="status">
                                Couldn't load more audit
                                history. Try again.
                            </p>
                        )}
                    </div>
                )}
        </section>
    )
}
