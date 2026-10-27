import { useState } from "react"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import type { AuthoringMutationStatus, RefreshOutcome } from "./useAuthoringMutation"
import { useAnnounceWhenRead, useConfirmedRefresh } from "./useConfirmedRefresh"

const CONFIRMED: AuthoringMutationStatus = { kind: "confirmed", refresh: "failed" }
const IDLE: AuthoringMutationStatus = { kind: "idle" }

function Harness({
    status,
    read,
    reset,
    pageStale,
    quietRecovery,
    message = "Party archived",
}: {
    status: AuthoringMutationStatus
    read: () => Promise<RefreshOutcome>
    reset: () => void
    pageStale?: boolean
    quietRecovery?: boolean
    message?: string | null
}) {
    const refreshed = useConfirmedRefresh({ status, reset, what: "party list", message, read, pageStale, quietRecovery })
    return (
        <div>
            {refreshed.notice}
            <span data-testid="held">{String(refreshed.held)}</span>
        </div>
    )
}

function renderWith(announce: (message: string) => void, ui: React.ReactElement) {
    return render(<AnnouncerContext.Provider value={{ announce }}>{ui}</AnnouncerContext.Provider>)
}

describe("useConfirmedRefresh", () => {
    it("shows nothing and holds nothing unless the write was confirmed without its read", () => {
        renderWith(vi.fn(), <Harness status={IDLE} read={async () => "ok"} reset={vi.fn()} />)
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(screen.getByTestId("held")).toHaveTextContent("false")
    })

    it("holds, says what was saved, and reads again without a write when Load latest is pressed", async () => {
        const announce = vi.fn()
        const reset = vi.fn()
        const read = vi.fn<() => Promise<RefreshOutcome>>().mockResolvedValue("ok")
        renderWith(announce, <Harness status={CONFIRMED} read={read} reset={reset} />)
        expect(screen.getByTestId("held")).toHaveTextContent("true")
        expect(screen.getByText(/Party archived\. The latest party list could not be loaded/)).toBeInTheDocument()
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        })
        expect(read).toHaveBeenCalledTimes(1)
        expect(reset).toHaveBeenCalledTimes(1)
        expect(announce).toHaveBeenCalledWith("Party archived")
    })

    it.each<RefreshOutcome>(["failed", "superseded"])(
        "stays held and announces nothing when the read answers %s",
        async (outcome) => {
            const announce = vi.fn()
            const reset = vi.fn()
            renderWith(announce, <Harness status={CONFIRMED} read={async () => outcome} reset={reset} />)
            await act(async () => {
                fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
            })
            expect(reset).not.toHaveBeenCalled()
            expect(announce).not.toHaveBeenCalled()
            expect(screen.getByTestId("held")).toHaveTextContent("true")
        },
    )

    it("treats a read that throws as a read that failed", async () => {
        const announce = vi.fn()
        const reset = vi.fn()
        renderWith(
            announce,
            <Harness
                status={CONFIRMED}
                read={async () => {
                    throw new Error("network")
                }}
                reset={reset}
            />,
        )
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        })
        expect(reset).not.toHaveBeenCalled()
        expect(announce).not.toHaveBeenCalled()
        expect(screen.getByRole("button", { name: "Load latest" })).toBeEnabled()
    })

    it("does not touch a component that went away while its read was in flight", async () => {
        const announce = vi.fn()
        const reset = vi.fn()
        let finish: (outcome: RefreshOutcome) => void = () => undefined
        const read = () => new Promise<RefreshOutcome>((resolve) => (finish = resolve))
        const view = renderWith(announce, <Harness status={CONFIRMED} read={read} reset={reset} />)
        fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        view.unmount()
        await act(async () => {
            finish("ok")
        })
        expect(reset).not.toHaveBeenCalled()
        expect(announce).not.toHaveBeenCalled()
    })

    it("is quiet and without a button while the page offers the read, and the first read that works recovers it once", () => {
        const announce = vi.fn()
        const props = { status: CONFIRMED, read: async (): Promise<RefreshOutcome> => "ok", reset: vi.fn() }
        const view = renderWith(announce, <Harness {...props} pageStale />)
        expect(screen.queryByRole("button", { name: "Load latest" })).toBeNull()
        expect(screen.getByTestId("held")).toHaveTextContent("true")

        view.rerender(
            <AnnouncerContext.Provider value={{ announce }}>
                <Harness {...props} pageStale={false} />
            </AnnouncerContext.Provider>,
        )
        expect(screen.getByTestId("held")).toHaveTextContent("false")
        expect(announce).toHaveBeenCalledTimes(1)
        expect(announce).toHaveBeenCalledWith("Party archived")

        // A failure of some later, unrelated read does not bring a resolved write back.
        view.rerender(
            <AnnouncerContext.Provider value={{ announce }}>
                <Harness {...props} pageStale />
            </AnnouncerContext.Provider>,
        )
        expect(screen.getByTestId("held")).toHaveTextContent("false")
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(announce).toHaveBeenCalledTimes(1)
    })

    it("ends the episode of a write the page's read recovered, so the next confirmed write is reported afresh (DEF-005)", () => {
        const announce = vi.fn()
        const read = async (): Promise<RefreshOutcome> => "ok"
        // A caller that keeps "saved, not yet read" in its own state: its status goes idle only when reset runs.
        function Caller({ pageStale, message }: { pageStale: boolean; message: string }) {
            const [unread, setUnread] = useState<string | null>(message)
            const refreshed = useConfirmedRefresh({
                status: unread === null ? IDLE : CONFIRMED,
                reset: () => setUnread(null),
                what: "party list",
                message: unread,
                read,
                pageStale,
            })
            return (
                <div>
                    {refreshed.notice}
                    <span data-testid="held">{String(refreshed.held)}</span>
                    <button type="button" onClick={() => setUnread("Second write saved")}>
                        second write
                    </button>
                </div>
            )
        }
        const wrap = (stale: boolean) => (
            <AnnouncerContext.Provider value={{ announce }}>
                <Caller pageStale={stale} message="First write saved" />
            </AnnouncerContext.Provider>
        )
        const view = render(wrap(true))
        expect(screen.getByTestId("held")).toHaveTextContent("true")
        view.rerender(wrap(false))
        expect(screen.getByTestId("held")).toHaveTextContent("false")
        expect(announce).toHaveBeenCalledWith("First write saved")
        expect(announce).toHaveBeenCalledTimes(1)

        // The second write is confirmed and the page's read has failed again.
        fireEvent.click(screen.getByRole("button", { name: "second write" }))
        view.rerender(wrap(true))
        expect(screen.getByTestId("held")).toHaveTextContent("true")
        expect(screen.getByText(/Second write saved\. The latest party list could not be loaded/)).toBeInTheDocument()
        view.rerender(wrap(false))
        expect(screen.getByTestId("held")).toHaveTextContent("false")
        expect(announce).toHaveBeenLastCalledWith("Second write saved")
        expect(announce).toHaveBeenCalledTimes(2)
    })

    it("leaves the announcement to the page when it is told the component will be gone", async () => {
        const announce = vi.fn()
        const reset = vi.fn()
        renderWith(announce, <Harness status={CONFIRMED} read={async () => "ok"} reset={reset} quietRecovery />)
        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Load latest" }))
        })
        expect(reset).toHaveBeenCalledTimes(1)
        expect(announce).not.toHaveBeenCalled()
    })

    it("says only 'Saved.' when it does not know what was saved", () => {
        renderWith(vi.fn(), <Harness status={CONFIRMED} read={async () => "ok"} reset={vi.fn()} message={null} />)
        expect(screen.getByText(/^Saved\. The latest party list could not be loaded/)).toBeInTheDocument()
    })
})

function Deferred({ fresh, token, message, then }: { fresh: boolean; token: unknown; message: string; then?: () => void }) {
    const defer = useAnnounceWhenRead(fresh, token)
    return (
        <button type="button" onClick={() => defer(message, then)}>
            defer
        </button>
    )
}

describe("useAnnounceWhenRead", () => {
    it("announces a deferred write only once a read has been applied, then runs what was waiting on it", () => {
        const announce = vi.fn()
        const then = vi.fn()
        const wrap = (fresh: boolean, token: unknown) => (
            <AnnouncerContext.Provider value={{ announce }}>
                <Deferred fresh={fresh} token={token} message="Session started" then={then} />
            </AnnouncerContext.Provider>
        )
        const view = render(wrap(false, "a"))
        fireEvent.click(screen.getByRole("button", { name: "defer" }))
        // Not fresh: a read is still outstanding (or has failed), so nothing is said.
        expect(announce).not.toHaveBeenCalled()
        expect(then).not.toHaveBeenCalled()

        view.rerender(wrap(true, "b"))
        expect(announce).toHaveBeenCalledTimes(1)
        expect(announce).toHaveBeenCalledWith("Session started")
        expect(then).toHaveBeenCalledTimes(1)

        // It is said once.
        view.rerender(wrap(true, "c"))
        expect(announce).toHaveBeenCalledTimes(1)
    })

    it("announces at once when the read was applied just before it was asked", () => {
        const announce = vi.fn()
        render(
            <AnnouncerContext.Provider value={{ announce }}>
                <Deferred fresh token="a" message="Ownership transferred" />
            </AnnouncerContext.Provider>,
        )
        fireEvent.click(screen.getByRole("button", { name: "defer" }))
        expect(announce).toHaveBeenCalledWith("Ownership transferred")
    })
})
