import { useState } from "react"
import { itemAuthoringPath, itemsPath, runItemOperation } from "../api/items"
import { apiRequest } from "../api/http"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { SessionParticipant } from "../types/campaignSession"
import type { ItemList, ItemView } from "../types/items"
import { useAnnounce } from "./authoring/announcer"
import { SelectField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    participants: SessionParticipant[]
}

interface Award {
    itemId: string
    holderId: string
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    item_already_placed: "That item already has a place. Move it from its own page.",
    item_destination_invalid: "Choose a published character.",
    clock_required: "Set the campaign time first.",
}

// Awards an unplaced, published item to a character in the session, from the run page. The
// campaign clock supplies the time. The item's current token is read just before the award so
// a change made elsewhere meanwhile is reported as stale instead of overwritten.
export function AwardItemSection({ campaignId, participants }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const items = useAuthoringResource<ItemList>(itemsPath(campaignId))
    const [itemId, setItemId] = useState("")
    const [holderId, setHolderId] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const present = participants.filter((p) => p.removed_at === null)
    const mutation = useAuthoringMutation<Award, ItemView>({
        scopeKey: `award-item:${campaignId}`,
        request: async (award, ctx) => {
            const current = await apiRequest<ItemView>("GET", itemAuthoringPath(campaignId, award.itemId))
            return runItemOperation(
                campaignId,
                award.itemId,
                "award",
                { expected_last_event_id: current.last_event_id, holder_entity_id: award.holderId },
                ctx,
            )
        },
        onSuccess: async () => {
            setItemId("")
            await items.refetch()
            announce("Item awarded")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    if (items.state.kind !== "ready") return null
    const available = items.state.data.items.filter(
        (item) =>
            item.canon_status === "canon" &&
            item.lifecycle_status === "active" &&
            item.holder_name === null &&
            !item.is_destroyed,
    )
    return (
        <section aria-labelledby="award-heading">
            <h2 id="award-heading">Award an item</h2>
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {available.length === 0 ? (
                <p>No published item is waiting to be awarded.</p>
            ) : (
                <form
                    noValidate
                    aria-label="Award an item"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (itemId === "" || holderId === "") {
                            setProblem("Choose an item and who receives it.")
                            return
                        }
                        setProblem(null)
                        mutation.submit({ itemId, holderId })
                    }}
                >
                    <SelectField
                        id="award-item"
                        label="Item"
                        value={itemId}
                        placeholder="Choose an item"
                        options={available.map((item) => ({
                            value: item.item_instance_id,
                            label: `${item.name} (${item.definition_name})`,
                        }))}
                        onChange={setItemId}
                        error={problem}
                    />
                    <SelectField
                        id="award-holder"
                        label="Award to"
                        value={holderId}
                        placeholder="Choose who receives it"
                        options={present.map((p) => ({ value: p.character_id, label: p.character_name }))}
                        onChange={setHolderId}
                    />
                    <button
                        type="submit"
                        className="authoring-button"
                        disabled={mutation.status.kind === "pending"}
                    >
                        Award item
                    </button>
                </form>
            )}
        </section>
    )
}
