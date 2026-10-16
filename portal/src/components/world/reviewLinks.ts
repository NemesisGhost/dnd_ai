import type { RevisionRow } from "../../types/review"

export interface ComparisonLink {
    from: number
    to: number
    // The text of the link.
    label: string
}

// Comparisons worth offering a reviewer, read from the record's own revision list (newest first,
// as the server returns it). Nothing is invented: a link exists only when the revisions it names
// exist.
//
// - the latest change against the version before it;
// - the current version against the newest version that moved the record to canon, when the record
//   was ever published and that version is not the current one.
export function comparisonLinks(revisions: readonly RevisionRow[]): ComparisonLink[] {
    const current = revisions[0]
    if (current === undefined) return []
    const links: ComparisonLink[] = []
    const previous = revisions[1]
    if (previous !== undefined) {
        links.push({
            from: previous.row_version,
            to: current.row_version,
            label: `Compare version ${current.row_version} with version ${previous.row_version}`,
        })
    }
    const published = revisions.find(
        (r, index) => index > 0 && r.kind === "lifecycle" && r.canon_status === "canon",
    )
    if (published !== undefined && published.row_version !== previous?.row_version) {
        links.push({
            from: published.row_version,
            to: current.row_version,
            label: `Compare with the version published as canon (version ${published.row_version})`,
        })
    }
    return links
}

// A one-line account of a revision, in the words the history page uses.
export function describeRevision(revision: RevisionRow, when: (iso: string) => string): string {
    const what =
        revision.kind === "created"
            ? "created"
            : revision.kind === "updated"
              ? "edited"
              : `status changed${revision.canon_status !== null ? ` to ${revision.canon_status.replace(/_/g, " ")}` : ""}${revision.lifecycle_status === "archived" ? ", archived" : ""}`
    return `Version ${revision.row_version}, ${what}, ${when(revision.created_at)}${
        revision.created_by_name !== null ? ` by ${revision.created_by_name}` : ""
    }`
}
