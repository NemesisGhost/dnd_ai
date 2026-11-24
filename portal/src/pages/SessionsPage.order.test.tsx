import {
    fireEvent,
    render,
    screen,
    within,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    describe,
    expect,
    it,
} from "vitest"
import type { CampaignSessionListItem } from "../types/campaignSession"
import { SessionsPage } from "./SessionsPage"

type Play = "unscheduled" | "scheduled" | "in_progress" | "completed"

interface Spec {
    n: number
    title?: string | null
    scheduled?: string | null
    started?: string | null
    ended?: string | null
    play?: Play
    actions?: CampaignSessionListItem["available_actions"]
    archived?: boolean
}

function session(spec: Spec): CampaignSessionListItem {
    return {
        session_id: `s${spec.n}`,
        session_number: spec.n,
        title: spec.title === undefined ? `Session ${spec.n}` : spec.title,
        status_code: spec.archived === true ? "archived" : "planned",
        started_at: spec.started ?? null,
        ended_at: spec.ended ?? null,
        scheduled_for: spec.scheduled ?? null,
        play_status: spec.play ?? "unscheduled",
        ...(spec.actions !== undefined ? { available_actions: spec.actions } : {}),
    }
}

function tree(sessions: CampaignSessionListItem[]) {
    return (
        <MemoryRouter initialEntries={["/app/c/sessions"]}>
            <Routes>
                <Route
                    path="/app/:campaignId/sessions"
                    element={<SessionsPage sessions={sessions} />}
                />
            </Routes>
        </MemoryRouter>
    )
}

// Displayed row order: the session id in each row's title link (the first link of the row), so equal titles stay
// distinguishable.
function order(): string[] {
    const table = screen.getByRole("table", { name: "Sessions" })
    return within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => {
            const href = within(row).getAllByRole("link")[0].getAttribute("href") ?? ""
            return href.replace("/app/c/sessions/", "")
        })
}

function heading(name: string): HTMLElement {
    return screen.getByRole("columnheader", { name: new RegExp(`^${name}`) })
}

function click(name: string) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name}`) }))
}

const ids = (...numbers: number[]) => numbers.map((n) => `s${n}`)

// Server order is session_number DESC.
const R1: Spec[] = [
    { n: 4 },
    { n: 3, scheduled: "2026-12-03T19:00:00Z", started: "2026-12-03T19:00:00Z", play: "completed" },
    { n: 2, scheduled: "2026-12-01T19:00:00Z", play: "scheduled" },
    { n: 1, scheduled: "2026-12-02T19:00:00Z", started: "2026-12-02T19:00:00Z", play: "completed" },
]

const TIES: Spec[] = [
    // shuffled on purpose
    { n: 7 },
    { n: 8, scheduled: "2026-12-05T19:00:00Z", play: "scheduled" },
    { n: 2, scheduled: "2026-12-01T19:00:00Z", play: "scheduled" },
    { n: 3 },
    { n: 4, scheduled: "2026-12-05T19:00:00.000+00:00", play: "scheduled" },
    { n: 1, scheduled: "2026-12-01T19:00:00.000+00:00", play: "scheduled" },
]

describe("SessionsPage default order and tie-break", () => {
    it("F1: opens by planned start ascending with unscheduled sessions last", () => {
        render(tree(R1.map(session)))
        expect(order()).toEqual(ids(2, 1, 3, 4))
    })

    it("F2: Planned start is the only heading with aria-sort, ascending with an up arrow", () => {
        render(tree(R1.map(session)))
        const sorted = screen
            .getAllByRole("columnheader")
            .filter((h) => h.hasAttribute("aria-sort"))
        expect(sorted).toEqual([heading("Planned start")])
        expect(heading("Planned start")).toHaveAttribute("aria-sort", "ascending")
        expect(heading("Planned start").textContent).toContain("▲")
    })

    it("F3: sessions at the same instant written differently order by session number in either input order", () => {
        const a = session({ n: 2, scheduled: "2026-12-01T19:00:00Z", play: "scheduled" })
        const b = session({ n: 1, scheduled: "2026-12-01T19:00:00.000+00:00", play: "scheduled" })
        const u3 = session({ n: 3 })
        const u5 = session({ n: 5 })
        const first = render(tree([u5, u3, a, b]))
        expect(order()).toEqual(ids(1, 2, 3, 5))
        first.unmount()
        render(tree([b, a, u5, u3]))
        expect(order()).toEqual(ids(1, 2, 3, 5))
    })

    it("F4: the scheduled session first, then unscheduled sessions by session number", () => {
        render(
            tree([
                session({ n: 7 }),
                session({ n: 3 }),
                session({ n: 8, scheduled: "2026-12-01T19:00:00Z", play: "scheduled" }),
                session({ n: 5 }),
            ]),
        )
        expect(order()).toEqual(ids(8, 3, 5, 7))
    })

    it("F5: orders by instant, not by the text of the timestamp", () => {
        render(
            tree([
                session({ n: 2, scheduled: "2026-12-01T20:00:00+02:00", play: "scheduled" }), // 18:00Z
                session({ n: 1, scheduled: "2026-12-01T19:00:00Z", play: "scheduled" }),
            ]),
        )
        expect(order()).toEqual(ids(2, 1))
    })

    it("F6: choosing Planned start toggles to descending; later first, unscheduled last, ties still ascending", () => {
        render(tree(TIES.map(session)))
        expect(order()).toEqual(ids(1, 2, 4, 8, 3, 7))
        click("Planned start")
        expect(heading("Planned start")).toHaveAttribute("aria-sort", "descending")
        expect(order()).toEqual(ids(4, 8, 1, 2, 3, 7))
    })

    it("F7: equal titles order by session number ascending in both directions", () => {
        render(
            tree([
                session({ n: 2, title: "Same" }),
                session({ n: 3, title: "Alpha" }),
                session({ n: 1, title: "Same" }),
            ]),
        )
        click("Title")
        expect(heading("Title")).toHaveAttribute("aria-sort", "ascending")
        expect(order()).toEqual(ids(3, 1, 2))
        click("Title")
        expect(heading("Title")).toHaveAttribute("aria-sort", "descending")
        expect(order()).toEqual(ids(1, 2, 3))
    })

    it("F8: ties in Start time, End time and Status follow session number in every direction; missing times last", () => {
        const T0 = "2026-11-01T18:00:00Z"
        const T1 = "2026-11-02T18:00:00Z"
        const rows = [
            session({ n: 5, started: T1, ended: T1, play: "completed" }),
            session({ n: 2, started: T1, ended: T1, play: "completed" }),
            session({ n: 4 }),
            session({ n: 1, started: T1, ended: T1, play: "completed" }),
            session({ n: 3 }),
            session({ n: 6, started: T0, ended: T0, play: "scheduled" }),
        ]
        render(tree(rows))
        for (const column of ["Start time", "End time"]) {
            click(column)
            expect(heading(column)).toHaveAttribute("aria-sort", "ascending")
            expect(order()).toEqual(ids(6, 1, 2, 5, 3, 4))
            click(column)
            expect(heading(column)).toHaveAttribute("aria-sort", "descending")
            expect(order()).toEqual(ids(1, 2, 5, 6, 3, 4))
        }
        click("Status")
        expect(order()).toEqual(ids(1, 2, 5, 6, 3, 4))
        click("Status")
        expect(order()).toEqual(ids(3, 4, 6, 1, 2, 5))
    })

    it("F9: an explicit sort stays applied when the rows are replaced", () => {
        const rows = [
            session({ n: 1, title: "Bravo" }),
            session({ n: 2, title: "Delta" }),
        ]
        const view = render(tree(rows))
        click("Title")
        expect(order()).toEqual(ids(1, 2))
        view.rerender(tree([...rows, session({ n: 3, title: "Charlie" })]))
        expect(order()).toEqual(ids(1, 3, 2))
        expect(heading("Title")).toHaveAttribute("aria-sort", "ascending")
    })

    it("F10: a new mount after an explicit sort opens with the default order", () => {
        const first = render(tree(R1.map(session)))
        click("Title")
        expect(heading("Title")).toHaveAttribute("aria-sort", "ascending")
        first.unmount()
        render(tree(R1.map(session)))
        expect(order()).toEqual(ids(2, 1, 3, 4))
        expect(heading("Planned start")).toHaveAttribute("aria-sort", "ascending")
        expect(heading("Title")).not.toHaveAttribute("aria-sort")
    })

    it("F11: every sort shows the same rows with Run links only where the server allows them", () => {
        const rows = [
            session({ n: 3, actions: ["update"], scheduled: "2026-12-03T19:00:00Z", play: "scheduled" }),
            session({ n: 2, actions: ["update", "start"], scheduled: "2026-12-02T19:00:00Z", play: "scheduled" }),
            session({ n: 1, actions: ["restore"], archived: true, play: "completed", started: "2026-11-01T18:00:00Z" }),
        ]
        render(tree(rows))
        const expected = ["s1", "s2", "s3"]
        for (const column of [null, "Title", "Status", "Start time", "End time", "Planned start"]) {
            if (column !== null) click(column)
            expect([...order()].sort()).toEqual(expected)
            const table = screen.getByRole("table", { name: "Sessions" })
            const runs = within(table)
                .getAllByRole("link")
                .filter((l) => l.getAttribute("href")?.endsWith("/run"))
            expect(runs.map((l) => l.getAttribute("href"))).toEqual(["s2/run"].map((p) => `/app/c/sessions/${p}`))
            expect(within(table).getByText("Completed (archived)")).toBeInTheDocument()
        }
    })

    it("F12: focus stays on the clicked heading button", () => {
        render(tree(R1.map(session)))
        const button = screen.getByRole("button", { name: /^Title/ })
        button.focus()
        fireEvent.click(button)
        expect(screen.getByRole("button", { name: /^Title/ })).toHaveFocus()
    })
})
