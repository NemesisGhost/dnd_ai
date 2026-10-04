import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { replacementCandidatesPath } from "../api/entityLifecycle"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { ReplacementCandidate, ReplacementCandidatePage } from "../types/entityLifecycle"
import { ConfirmDialog } from "./authoring/ConfirmDialog"
import { TextField } from "./authoring/fields"
import "./authoring/authoring.css"

interface SupersedeEntityDialogProps {
    open: boolean
    campaignId: string
    entityId: string
    entityName: string
    onConfirm: (replacement: ReplacementCandidate) => void
    onCancel: () => void
    pending: boolean
    error: ReactNode
}

// Choose the canon record that replaces this one. Candidates come from the
// server (same world, same type, canon, not this record); the portal never
// guesses which records are eligible. The server re-validates at submit.
export function SupersedeEntityDialog(props: SupersedeEntityDialogProps) {
    return props.open ? <OpenDialog {...props} /> : null
}

function OpenDialog({
    campaignId,
    entityId,
    entityName,
    onConfirm,
    onCancel,
    pending,
    error,
}: SupersedeEntityDialogProps) {
    const [search, setSearch] = useState("")
    const [debounced, setDebounced] = useState("")
    const [chosen, setChosen] = useState<string | null>(null)

    useEffect(() => {
        const id = window.setTimeout(() => setDebounced(search), 250)
        return () => window.clearTimeout(id)
    }, [search])

    const { state } = useAuthoringResource<ReplacementCandidatePage>(
        replacementCandidatesPath(campaignId, entityId, debounced),
    )
    const items = state.kind === "ready" ? state.data.items : []
    const selected = items.find((c) => c.entity_id === chosen) ?? null

    return (
        <ConfirmDialog
            open
            title={`Replace ${entityName}?`}
            description="The chosen record becomes the current canon; this one is kept as superseded history."
            confirmLabel="Supersede"
            onConfirm={() => selected !== null && onConfirm(selected)}
            onCancel={onCancel}
            pending={pending}
            error={error}
            confirmDisabled={selected === null}
        >
            <TextField label="Search replacements" value={search} onChange={setSearch} />
            {state.kind === "loading" ? <p role="status">Loading candidates…</p> : null}
            {state.kind === "error" || state.kind === "unavailable" || state.kind === "denied" ? (
                <p role="alert">Replacement candidates are not available.</p>
            ) : null}
            {state.kind === "ready" && items.length === 0 ? (
                <p>No eligible replacements. A replacement must be another canon record of the same kind.</p>
            ) : null}
            {items.length > 0 ? (
                <fieldset className="authoring-field">
                    <legend className="authoring-field__label">Replacement</legend>
                    {items.map((candidate) => (
                        <label className="authoring-radio" key={candidate.entity_id}>
                            <input
                                type="radio"
                                name="replacement"
                                checked={chosen === candidate.entity_id}
                                onChange={() => setChosen(candidate.entity_id)}
                            />
                            <span>{candidate.canonical_name}</span>
                        </label>
                    ))}
                </fieldset>
            ) : null}
        </ConfirmDialog>
    )
}
