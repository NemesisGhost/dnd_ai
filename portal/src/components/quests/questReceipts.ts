import type { QuestAction } from "../../types/questRuntime"

// What a confirmed quest status change leaves on the page: built from the request that was confirmed and
// the server's receipt, never from whatever scope is selected when the answer arrives.
export interface QuestReceipt {
    id: string
    action: QuestAction
    // "Everyone" or the party's name, from the party the request named.
    who: string
    previous: string | null
    status: string
    // False when the server found nothing to change (the status was already that).
    changed: boolean
    eventId: string
    // Whether progress was read again after the change, so what is shown is up to date.
    readBack: boolean
    // The line about authored rewards not being applied, or null when it does not apply.
    rewardsLine: string | null
}

const PAST: Readonly<Record<QuestAction, string>> = {
    activate: "activated",
    complete: "completed",
    fail: "failed",
    suspend: "suspended",
    resume: "resumed",
    abandon: "abandoned",
}

export const receiptHeadingText = (action: QuestAction, who: string): string =>
    `Recorded: quest ${PAST[action]} for ${who}`

export const receiptHeadingId = (id: string): string => `quest-receipt-${id}`
