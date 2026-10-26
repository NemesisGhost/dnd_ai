import type {
    EventExplanation as EventExplanationData,
    ExplanationClockTime,
    ExplanationRef,
} from "../../types/eventExplanation"

export const NOT_RECORDED = "not recorded"
export const NOT_AVAILABLE = "not available"

const refName = (ref: ExplanationRef | null, fallback: string): string =>
    ref !== null && ref.state === "named" && ref.name !== null ? ref.name : fallback

export const timeName = (time: ExplanationClockTime | null): string =>
    time !== null && time.state === "named" && time.text !== null
        ? time.text
        : time?.state === "unrecorded"
          ? NOT_RECORDED
          : NOT_AVAILABLE

// The one-line account of what happened, as plain text (also used where a link cannot go).
export function explanationSentence(x: EventExplanationData): string | null {
    const who = refName(x.subject, "A character")
    switch (x.family) {
        case "party_member_joined":
            return `${who} joined ${refName(x.party, "a party")}.`
        case "party_member_left":
            return `${who} left ${refName(x.party, "a party")}.`
        case "character_build_activated":
            if (x.build_detail !== "full") return `${possessive(who)} build changed.`
            return `${possessive(who)} active build changed from ${buildName(x.previous_build)} to ${buildName(x.new_build)}.`
        case "campaign_clock_advanced":
            return clockSentence("advanced", x)
        case "campaign_clock_corrected":
            return clockSentence("was corrected", x)
        default:
            return null
    }
}

const possessive = (name: string): string => (name === "A character" ? "A character's" : `${name}'s`)

export function buildName(ref: ExplanationRef | null): string {
    if (ref === null) return NOT_AVAILABLE
    if (ref.state === "unrecorded") return "no earlier build recorded"
    return ref.state === "named" && ref.name !== null ? ref.name : "a build that is not available"
}

function clockSentence(verb: string, x: EventExplanationData): string {
    const from = x.previous_time
    const to = timeName(x.new_time)
    if (from === null || from.state === "unrecorded") {
        return `The campaign clock ${verb === "advanced" ? "was set" : "was corrected"} to ${to} (no earlier time recorded).`
    }
    return `The campaign clock ${verb} from ${timeName(from)} to ${to}.`
}

