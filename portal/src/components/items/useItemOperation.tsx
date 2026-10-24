import { useRef, useState } from "react"
import type { ReactNode } from "react"
import { runItemOperation } from "../../api/items"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { ItemView, OperationBody } from "../../types/items"
import { useAnnounce } from "../authoring/announcer"
import { MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import type { ItemSection } from "./itemStages"

export const CODE_MESSAGE: Readonly<Record<string, string>> = {
    item_destroyed: "This item is destroyed.",
    item_already_placed: "This item already has a place. Move it instead.",
    item_not_held: "A character has to be carrying this item for that.",
    item_equipped: "Unequip the item first.",
    item_attuned: "End the attunement first.",
    item_operation_invalid: "That cannot be done to this item as it is now.",
    attunement_not_allowed:
        "This item cannot be attuned right now (it may not need attunement, may already be attuned, or the character has three attuned items).",
    item_destination_invalid: "Choose a published character or place in this world.",
    item_container_invalid: "That item cannot be placed in that container.",
    clock_required: "Set the campaign time first, or choose a time above.",
}

// One command against the item: the operation, its body, the announcement on success, the section
// that sent it (its error and its validation messages appear there), and what to clear once the
// server has confirmed it.
export interface ItemCommand {
    operation: string
    body: Record<string, unknown>
    done: string
    section: ItemSection
    after?: () => void
}

// A command as submitted: the complete request (the operation's body with the item token and the
// chosen time) is captured here, once. A retry replays exactly this, with its idempotency key; a
// deliberate new submission with different data builds a new one and so gets a new key.
interface PreparedCommand extends ItemCommand {
    request: OperationBody
}

export interface ItemOperations {
    run: (command: ItemCommand) => void
    busy: boolean
    // A client-side validation message for a section (nothing was sent).
    reject: (section: ItemSection, message: string) => void
    // The error or validation message belonging to `section`, if any.
    feedback: (section: ItemSection) => ReactNode
}

// The one mutation behind every Use-in-play control. Each command names the last event this page
// saw, so a change made elsewhere meanwhile is reported as stale instead of overwritten, and
// optionally a world time (omitted: the campaign clock). Nothing here assumes a command worked:
// the page refetches the item and shows what the server now holds.
export function useItemOperations({
    campaignId,
    view,
    when,
    consumeTime,
    refetch,
}: {
    campaignId: string
    view: ItemView
    when: string
    // Clears the chosen time once a command has used it, so the next one defaults to the campaign clock.
    consumeTime: () => void
    refetch: () => Promise<unknown>
}): ItemOperations {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [problem, setProblem] = useState<{ section: ItemSection; message: string } | null>(null)
    const current = useRef<PreparedCommand | null>(null)
    // The section whose command last ran, so its refusal is shown there and nowhere else.
    const [errorSection, setErrorSection] = useState<ItemSection | null>(null)

    const mutation = useAuthoringMutation<PreparedCommand, unknown>({
        scopeKey: `item-operation:${view.item_instance_id}`,
        request: (command, ctx) =>
            runItemOperation(campaignId, view.item_instance_id, command.operation, command.request, ctx),
        onSuccess: async () => {
            const command = current.current
            current.current = null
            command?.after?.()
            // A refused or failed command keeps its time; only a confirmed one consumes it.
            consumeTime()
            await refetch()
            if (command !== null && command !== undefined) announce(command.done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null

    return {
        busy: mutation.status.kind === "pending",
        run(command) {
            setProblem(null)
            const prepared: PreparedCommand = {
                ...command,
                request: {
                    expected_last_event_id: view.last_event_id,
                    ...(when === "" ? {} : { world_time_id: when }),
                    ...command.body,
                },
            }
            current.current = prepared
            setErrorSection(command.section)
            mutation.submit(prepared)
        },
        reject(section, message) {
            setProblem({ section, message })
        },
        feedback(section) {
            if (problem !== null && problem.section === section) return <p role="alert">{problem.message}</p>
            if (error === null || errorSection !== section) return null
            if (error.kind === "stale") {
                return (
                    <StaleWriteNotice
                        onLoadLatest={() => {
                            mutation.reset()
                            void refetch()
                        }}
                    />
                )
            }
            const explained = error.code ? (CODE_MESSAGE[error.code] ?? null) : null
            if (explained !== null) return <p role="alert">{explained}</p>
            return <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        },
    }
}
