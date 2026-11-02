import { describe, expect, it } from "vitest"
import type { RevisionRow } from "../../types/review"
import { comparisonLinks, describeRevision } from "./reviewLinks"

const rev = (row_version: number, kind: string, canon: string | null = null, extra: Partial<RevisionRow> = {}): RevisionRow => ({
    row_version,
    kind,
    created_at: "2026-01-02T10:00:00Z",
    created_by_name: "Gina",
    canon_status: canon,
    lifecycle_status: canon === null ? null : "active",
    ...extra,
})

describe("comparisonLinks", () => {
    it("offers nothing for a record with no revisions or only one", () => {
        expect(comparisonLinks([])).toEqual([])
        expect(comparisonLinks([rev(1, "created")])).toEqual([])
    })

    it("offers the latest change against the one before it", () => {
        const links = comparisonLinks([rev(3, "lifecycle", "proposed"), rev(2, "updated"), rev(1, "created")])
        expect(links).toEqual([{ from: 2, to: 3, label: "Compare version 3 with version 2" }])
    })

    it("offers the version published as canon only when the record was ever published", () => {
        const never = comparisonLinks([rev(3, "updated"), rev(2, "lifecycle", "draft"), rev(1, "created")])
        expect(never.map((l) => l.from)).toEqual([2])
        const published = comparisonLinks([
            rev(5, "updated"),
            rev(4, "updated"),
            rev(3, "lifecycle", "canon"),
            rev(2, "lifecycle", "approved"),
            rev(1, "created"),
        ])
        expect(published).toEqual([
            { from: 4, to: 5, label: "Compare version 5 with version 4" },
            { from: 3, to: 5, label: "Compare with the version published as canon (version 3)" },
        ])
    })

    it("does not offer the same pair twice or compare the current version with itself", () => {
        const justPublished = comparisonLinks([rev(3, "lifecycle", "canon"), rev(2, "lifecycle", "approved"), rev(1, "created")])
        expect(justPublished).toEqual([{ from: 2, to: 3, label: "Compare version 3 with version 2" }])
        const editedOnce = comparisonLinks([rev(4, "updated"), rev(3, "lifecycle", "canon"), rev(2, "x"), rev(1, "created")])
        expect(editedOnce).toHaveLength(1)
    })
})

describe("describeRevision", () => {
    const when = () => "TIME"
    it("says what each kind of revision was and who made it", () => {
        expect(describeRevision(rev(1, "created"), when)).toBe("Version 1, created, TIME by Gina")
        expect(describeRevision(rev(2, "updated"), when)).toBe("Version 2, edited, TIME by Gina")
        expect(describeRevision(rev(3, "lifecycle", "proposed"), when)).toBe(
            "Version 3, status changed to proposed, TIME by Gina",
        )
        expect(describeRevision(rev(4, "lifecycle", "canon", { lifecycle_status: "archived" }), when)).toBe(
            "Version 4, status changed to canon, archived, TIME by Gina",
        )
    })

    it("does not invent an author", () => {
        expect(describeRevision(rev(1, "created", null, { created_by_name: null }), when)).toBe("Version 1, created, TIME")
    })
})
