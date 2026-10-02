// Derives the profile-menu avatar and initials from the bootstrap display
// name only (UI_DESIGN §4.2). No SessionBootstrap field is added for this
// — imageUrl exists only so a future profile-image contract slots in
// without restructuring the menu.

export type ProfileAvatarModel =
    | { kind: "image"; url: string }
    | { kind: "initials"; text: string }
    | { kind: "icon" }

function firstGrapheme(word: string): string {
    if (
        typeof Intl !== "undefined" &&
        typeof Intl.Segmenter === "function"
    ) {
        const segmenter = new Intl.Segmenter(
            undefined,
            { granularity: "grapheme" },
        )
        const segments = segmenter.segment(word)
        const first = segments[Symbol.iterator]().next()

        if (!first.done) {
            return first.value.segment
        }

        return ""
    }

    const graphemes = Array.from(word)
    return graphemes[0] ?? ""
}

function containsLetterOrNumber(word: string): boolean {
    return /[\p{L}\p{N}]/u.test(word)
}

export function deriveInitials(
    displayName: string,
): string | null {
    const words = displayName
        .trim()
        .split(/\s+/u)
        .filter((word) => word.length > 0 && containsLetterOrNumber(word))

    if (words.length === 0) {
        return null
    }

    const first = words[0]!
    const last = words[words.length - 1]!

    const initials =
        words.length === 1
            ? firstGrapheme(first)
            : `${firstGrapheme(first)}${firstGrapheme(last)}`

    const trimmed = initials.slice(0, 2)

    return trimmed.length > 0
        ? trimmed.toLocaleUpperCase()
        : null
}

export interface DeriveProfileAvatarOptions {
    displayName: string
    imageUrl?: string | null
}

export function deriveProfileAvatar({
    displayName,
    imageUrl = null,
}: DeriveProfileAvatarOptions): ProfileAvatarModel {
    if (typeof imageUrl === "string" && imageUrl.length > 0) {
        return { kind: "image", url: imageUrl }
    }

    const initials = deriveInitials(displayName)

    if (initials !== null) {
        return { kind: "initials", text: initials }
    }

    return { kind: "icon" }
}
