import { useEffect } from "react"

// Titles belong to terminal states only (docs/UI_DESIGN.md, "Unavailable and unauthorized destinations").
const TITLE_SUFFIX = "portal"

// Sets the document title for as long as the calling component is mounted and puts the previous
// one back when it unmounts, so a terminal state never leaves its title on a later page. Titles are
// only ever static, generic phrases: never a name, an identifier or anything the server sent about
// a record the person cannot see.
export function useDocumentTitle(title: string | null): void {
    useEffect(() => {
        if (title === null) {
            return
        }
        const previous = document.title
        document.title = `${title} · ${TITLE_SUFFIX}`
        return () => {
            document.title = previous
        }
    }, [title])
}
