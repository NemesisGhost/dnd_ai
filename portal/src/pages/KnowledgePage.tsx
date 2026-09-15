import { useId } from "react"
import type { ReactNode } from "react"
import type { AuthorizedParty } from "../types/bootstrap"
import type { KnowledgeView } from "../types/knowledge"

interface KnowledgePageProps {
    view: KnowledgeView
    query: string
    partyId: string | null
    parties: AuthorizedParty[]
    onViewChange: (view: KnowledgeView) => void
    onQueryChange: (query: string) => void
    onPartyChange: (partyId: string | null) => void
    children: ReactNode
}

interface ViewOption {
    value: KnowledgeView
    label: string
}

const viewOptions: ViewOption[] = [
    { value: "known", label: "Known" },
    { value: "rumors", label: "Rumors" },
    { value: "party_shared", label: "Party shared" },
    { value: "character_private", label: "Character private" },
    { value: "recent", label: "Recent" },
    { value: "public", label: "Public" },
]

export function KnowledgePage({
    view,
    query,
    partyId,
    parties,
    onViewChange,
    onQueryChange,
    onPartyChange,
    children,
}: KnowledgePageProps) {
    const viewSelectId = useId()
    const searchInputId = useId()
    const partySelectId = useId()

    const hasParties = parties.length > 0

    return (
        <section aria-labelledby="knowledge-heading">
            <h1 id="knowledge-heading">Knowledge</h1>

            <div
                className="knowledge-page__filters"
                role="search"
                aria-label="Knowledge search"
            >
                <div className="knowledge-page__field">
                    <label htmlFor={viewSelectId}>
                        View
                    </label>
                    <select
                        id={viewSelectId}
                        value={view}
                        onChange={(event) =>
                            onViewChange(
                                event.currentTarget
                                    .value as KnowledgeView,
                            )
                        }
                    >
                        {viewOptions.map((option) => (
                            <option
                                key={option.value}
                                value={option.value}
                            >
                                {option.label}
                            </option>
                        ))}
                    </select>
                </div>

                <div className="knowledge-page__field">
                    <label htmlFor={searchInputId}>
                        Search
                    </label>
                    <input
                        id={searchInputId}
                        type="search"
                        value={query}
                        onChange={(event) =>
                            onQueryChange(event.currentTarget.value)
                        }
                    />
                </div>

                <div className="knowledge-page__field">
                    <label htmlFor={partySelectId}>
                        Party
                    </label>
                    <select
                        id={partySelectId}
                        value={partyId ?? ""}
                        disabled={!hasParties}
                        onChange={(event) => {
                            const value = event.currentTarget.value

                            onPartyChange(
                                value === "" ? null : value,
                            )
                        }}
                    >
                        <option
                            value=""
                            disabled={!hasParties}
                        >
                            {hasParties
                                ? "No party selected"
                                : "No party available"}
                        </option>

                        {parties.map((party) => (
                            <option
                                key={party.party_id}
                                value={party.party_id}
                            >
                                {party.party_name}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {children}
        </section>
    )
}
