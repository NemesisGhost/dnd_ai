import { useRef, useState } from "react"
import { itemAuthoringPath, itemsPath, runItemOperation } from "../api/items"
import { apiRequest } from "../api/http"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { SessionParticipantPick } from "../types/campaignSession"
import type { ItemList, ItemView } from "../types/items"
import { useAnnounce } from "./authoring/announcer"
import { SelectField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    participants: SessionParticipantPick[]
    // False when a surrounding panel supplies the section heading.
    showHeading?: boolean
}

// The whole request: what to award, to whom, and the item version it was prepared against.
// Retry and an unchanged resubmission send exactly this, so the body never changes under a key.
interface Award {
    itemId: string
    holderId: string
    expectedLastEventId: string | null
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    item_already_placed: "That item already has a place. Move it from its own page.",
    item_destination_invalid: "Choose a published character.",
    clock_required: "Set the campaign time first.",
}

// Awards an unplaced, published item to a character in the session, from the run page. The
// campaign clock supplies the time. The item's current token is read once, when the award is
// prepared, so a change made elsewhere meanwhile is reported as stale instead of overwritten. That
// prepared award is then the request: if the answer is lost, Retry (or pressing Award again) sends
// the same token, target, body and key, and never reads a new token under the old key.
export function AwardItemSection({ campaignId, participants, showHeading = true }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const items = useAuthoringResource<ItemList>(itemsPath(campaignId))
    const [itemId, setItemId] = useState("")
    const [holderId, setHolderId] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const [preparing, setPreparing] = useState(false)
    const [prepareFailed, setPrepareFailed] = useState(false)
    const prepared = useRef<Award | null>(null)
    const present = participants.filter((p) => p.removed_at === null)
    const mutation = useAuthoringMutation<Award, ItemView>({
        scopeKey: `award-item:${campaignId}`,
        request: (award, ctx) =>
            runItemOperation(
                campaignId,
                award.itemId,
                "award",
                { expected_last_event_id: award.expectedLastEventId, holder_entity_id: award.holderId },
                ctx,
            ),
        onSuccess: async () => {
            prepared.current = null
            setItemId("")
            const outcome = await items.refetch()
            if (outcome !== "ok") return outcome
            announce("Item awarded")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    async function submitAward() {
        if (itemId === "" || holderId === "") {
            setProblem("Choose an item and who receives it.")
            return
        }
        setProblem(null)
        setPrepareFailed(false)
        const earlier = prepared.current
        if (earlier !== null && error !== null && (error.kind === "network" || error.kind === "server")) {
            // An award whose answer was lost may have happened: send that one again, unchanged.
            mutation.submit(earlier)
            return
        }
        setPreparing(true)
        try {
            const current = await apiRequest<ItemView>("GET", itemAuthoringPath(campaignId, itemId))
            const award = { itemId, holderId, expectedLastEventId: current.last_event_id }
            prepared.current = award
            mutation.submit(award)
        } catch {
            setPrepareFailed(true)
        } finally {
            setPreparing(false)
        }
    }
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    if (items.state.kind === "loading") return <p role="status">Loading items…</p>
    if (items.state.kind !== "ready") return <p role="alert">Items could not be loaded.</p>
    const available = items.state.data.items.filter(
        (item) =>
            item.canon_status === "canon" &&
            item.lifecycle_status === "active" &&
            item.holder_name === null &&
            !item.is_destroyed,
    )
    // A surrounding panel supplies the heading and landmark when this one is hidden.
    const Wrapper = showHeading ? "section" : "div"
    return (
        <Wrapper aria-labelledby={showHeading ? "award-heading" : undefined}>
            {showHeading ? <h2 id="award-heading">Award an item</h2> : null}
            {prepareFailed ? <p role="alert">The item could not be checked, so nothing was awarded. Try again.</p> : null}
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
                        if (!preparing) void submitAward()
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
                        disabled={mutation.status.kind === "pending" || preparing}
                    >
                        Award item
                    </button>
                </form>
            )}
        </Wrapper>
    )
}
