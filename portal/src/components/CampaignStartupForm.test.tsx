import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useEffect, useState } from "react"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { UserPreferenceRequestError } from "../api/userPreferences"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { CampaignStartupForm } from "./CampaignStartupForm"

const { setPreferenceMock } = vi.hoisted(() => ({ setPreferenceMock: vi.fn() }))

vi.mock("../api/userPreferences", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/userPreferences")>()
    return { ...actual, setCampaignStartupPreference: setPreferenceMock }
})

const alpha: CampaignContext = {
    ...sessionBootstrapFixture.campaigns[0]!,
    campaign_id: "campaign-a",
    campaign_name: "Alpha Campaign",
}
const beta: CampaignContext = {
    ...alpha,
    campaign_id: "campaign-b",
    campaign_name: "Beta Campaign",
}

function makeBootstrap(overrides: Partial<SessionBootstrap> = {}): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        startup_campaign_id: null,
        campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: null,
        },
        campaigns: [alpha, beta],
        ...overrides,
    }
}

const onCheckSession = vi.fn()

// Mirrors the real provider: a successful refresh replaces the shared
// bootstrap with the server's view of what was just saved.
let serverPreferred: string | null = null
const refreshOutcome: { fail: boolean; unapplied: boolean } = { fail: false, unapplied: false }

function withServerPreference(base: SessionBootstrap): SessionBootstrap {
    return {
        ...base,
        campaign_preferences: {
            ...base.campaign_preferences,
            startup_mode: serverPreferred === null ? "resume_last_visited" : "preferred_campaign",
            preferred_campaign_id: serverPreferred,
        },
    }
}

function acceptSaves(): void {
    setPreferenceMock.mockImplementation(async (id: string | null) => {
        serverPreferred = id
    })
}

// What a later session read publishes, from outside the form (another owner of the shared bootstrap).
const bus: { publish: (next: SessionBootstrap) => void } = { publish: () => undefined }
const publish = (next: SessionBootstrap) => bus.publish(next)
// Every read the form asked for through the session, with its signal.
const refreshCalls: Array<AbortSignal | undefined> = []

function Harness({ initial }: { initial: SessionBootstrap }) {
    const [bootstrap, setBootstrap] = useState(initial)
    useEffect(() => {
        bus.publish = setBootstrap
    }, [])
    const refresh = async (signal?: AbortSignal): Promise<boolean> => {
        refreshCalls.push(signal)
        if (refreshOutcome.fail) {
            throw new Error("offline")
        }
        if (refreshOutcome.unapplied) {
            return false
        }
        setBootstrap((current) => withServerPreference(current))
        return true
    }
    return (
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap },
                reload: vi.fn(),
                refresh,
            }}
        >
            <MemoryRouter>
                {/* The Settings page puts the form in a section; the recovery focus handoff resolves within it. */}
                <section>
                    <CampaignStartupForm bootstrap={bootstrap} onCheckSession={onCheckSession} />
                </section>
            </MemoryRouter>
        </SessionContext.Provider>
    )
}

function renderForm(bootstrap: SessionBootstrap = makeBootstrap()) {
    serverPreferred = bootstrap.campaign_preferences.preferred_campaign_id
    return render(<Harness initial={bootstrap} />)
}

const resumeRadio = () =>
    screen.getByRole("radio", { name: "Resume my last visited campaign" })
const fixedRadio = () => screen.getByRole("radio", { name: "Always open this campaign" })
const campaignSelect = () => screen.getByRole("combobox", { name: "Campaign" })
const saveButton = () => screen.getByRole("button", { name: /save startup preference/i })

beforeEach(() => {
    setPreferenceMock.mockReset()
    onCheckSession.mockReset()
    refreshCalls.length = 0
    refreshOutcome.fail = false
    refreshOutcome.unapplied = false
    acceptSaves()
})

describe("CampaignStartupForm initial state", () => {
    it("starts on resume with the selector disabled and nothing to save", () => {
        renderForm()

        expect(resumeRadio()).toBeChecked()
        expect(fixedRadio()).not.toBeChecked()
        expect(campaignSelect()).toBeDisabled()
        expect(saveButton()).toBeDisabled()
    })

    it("reflects a stored preferred campaign", () => {
        renderForm(
            makeBootstrap({
                campaign_preferences: {
                    startup_mode: "preferred_campaign",
                    preferred_campaign_id: "campaign-b",
                    last_visited_campaign_id: null,
                },
            }),
        )

        expect(fixedRadio()).toBeChecked()
        expect(campaignSelect()).toBeEnabled()
        expect(campaignSelect()).toHaveValue("campaign-b")
        expect(campaignSelect()).toBeRequired()
    })

    it("offers only bootstrap campaigns by name, never raw ids", () => {
        const { container } = renderForm()

        const options = within(campaignSelect())
            .getAllByRole("option")
            .map((option) => option.textContent)
        expect(options).toEqual(["Choose a campaign", "Alpha Campaign", "Beta Campaign"])
        expect(container.textContent).not.toContain("campaign-a")
    })

    it("explains the single-campaign case while keeping the form usable", () => {
        renderForm(makeBootstrap({ campaigns: [alpha] }))

        expect(
            screen.getByText("You have one campaign, so it always opens at sign-in."),
        ).toBeInTheDocument()
        expect(resumeRadio()).toBeInTheDocument()
    })

    it("shows an empty state and no form when there are no campaigns", () => {
        renderForm(makeBootstrap({ campaigns: [] }))

        expect(
            screen.getByText(/You do not have access to any campaigns yet/),
        ).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Go to campaigns" })).toHaveAttribute(
            "href",
            "/campaigns",
        )
        expect(screen.queryByRole("radio")).not.toBeInTheDocument()
        expect(screen.queryByRole("button")).not.toBeInTheDocument()
    })
})

describe("CampaignStartupForm choosing and saving", () => {
    it("enables the selector for fixed mode but needs a campaign before saving", () => {
        renderForm()

        fireEvent.click(fixedRadio())

        expect(campaignSelect()).toBeEnabled()
        expect(campaignSelect()).toHaveValue("")
        expect(saveButton()).toBeDisabled()

        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })

        expect(saveButton()).toBeEnabled()
    })

    it("saves the chosen campaign, reports success, and treats it as the new baseline", async () => {
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())

        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent(
                "Startup preference saved.",
            )
        })
        expect(setPreferenceMock).toHaveBeenCalledWith(
            "campaign-b",
            sessionBootstrapFixture.csrf_token,
            expect.anything(),
        )
        expect(saveButton()).toBeDisabled()
        expect(fixedRadio()).toBeChecked()
    })

    it("saves null when returning to resume", async () => {
        renderForm(
            makeBootstrap({
                campaign_preferences: {
                    startup_mode: "preferred_campaign",
                    preferred_campaign_id: "campaign-a",
                    last_visited_campaign_id: null,
                },
            }),
        )

        fireEvent.click(resumeRadio())
        fireEvent.click(saveButton())

        await waitFor(() => {
            expect(setPreferenceMock).toHaveBeenCalledWith(
                null,
                sessionBootstrapFixture.csrf_token,
                expect.anything(),
            )
        })
    })

    it("disables controls and shows pending while saving", async () => {
        let resolve: () => void = () => {}
        setPreferenceMock.mockReturnValue(
            new Promise<void>((r) => {
                resolve = r
            }),
        )
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())

        expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled()
        expect(campaignSelect()).toBeDisabled()
        expect(screen.getByRole("status")).toHaveTextContent(
            "Saving your startup preference…",
        )

        resolve()
        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent("saved")
        })
    })

    it("clears the success message when the choice changes again", async () => {
        renderForm()
        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())
        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent("saved")
        })

        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })

        expect(screen.getByRole("status")).toBeEmptyDOMElement()
        expect(saveButton()).toBeEnabled()
    })
})

describe("CampaignStartupForm failures", () => {
    it("drops a campaign the server reports unavailable and explains why", async () => {
        setPreferenceMock.mockRejectedValue(new UserPreferenceRequestError(404, "gone"))
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "That campaign is no longer available.",
        )
        expect(
            within(campaignSelect())
                .getAllByRole("option")
                .map((option) => option.textContent),
        ).toEqual(["Choose a campaign", "Alpha Campaign"])
        expect(campaignSelect()).toHaveValue("")
    })

    it("offers a session check when the save is refused", async () => {
        setPreferenceMock.mockRejectedValue(new UserPreferenceRequestError(401, "no"))
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "Your session could not be verified, so nothing was saved.",
        )
        fireEvent.click(screen.getByRole("button", { name: "Check my session" }))
        expect(onCheckSession).toHaveBeenCalledTimes(1)
    })

    it("keeps the chosen values and allows a retry after a recoverable error", async () => {
        setPreferenceMock.mockRejectedValueOnce(new UserPreferenceRequestError(500, "boom"))
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "Your preference could not be saved. Try again.",
        )
        expect(campaignSelect()).toHaveValue("campaign-a")
        expect(saveButton()).toBeEnabled()

        fireEvent.click(saveButton())

        await waitFor(() => {
            expect(screen.getByRole("status")).toHaveTextContent("saved")
        })
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("does not report success or apply the choice when the session refresh fails", async () => {
        refreshOutcome.fail = true
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "could not be confirmed",
        )
        expect(screen.getByRole("status")).toBeEmptyDOMElement()
        // Still the user's draft, still retryable; nothing authoritative changed.
        expect(campaignSelect()).toHaveValue("campaign-b")
        expect(saveButton()).toBeEnabled()
        // Check my session re-reads in place for an unconfirmed save; it never reloads the page.
        const reads = refreshCalls.length
        fireEvent.click(screen.getByRole("button", { name: "Check my session" }))
        await waitFor(() => expect(refreshCalls.length).toBe(reads + 1))
        expect(onCheckSession).not.toHaveBeenCalled()
    })

    it("says the confirmed save happened, and never that nothing was saved, when the refresh was not applied", async () => {
        refreshOutcome.unapplied = true
        acceptSaves()
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())

        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("Your preference was saved")
        expect(alert).toHaveTextContent("could not be confirmed")
        expect(alert).not.toHaveTextContent("nothing was saved")
        expect(screen.getByRole("status")).toBeEmptyDOMElement()
        // The newer draft is kept and the write is not repeated to repair the read.
        expect(campaignSelect()).toHaveValue("campaign-b")
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
        const reads = refreshCalls.length
        fireEvent.click(screen.getByRole("button", { name: "Check my session" }))
        await waitFor(() => expect(refreshCalls.length).toBe(reads + 1))
        expect(onCheckSession).not.toHaveBeenCalled()
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("still reports a rejected save as refused, with nothing saved", async () => {
        setPreferenceMock.mockRejectedValue(new UserPreferenceRequestError(403, "no"))
        renderForm()

        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())

        expect(await screen.findByRole("alert")).toHaveTextContent("nothing was saved")
    })
})


// P15-C03-S02-T01: a confirmed save whose read-back was not applied stays an outstanding episode until the
// shared session shows the saved value for the same user.
describe("CampaignStartupForm unconfirmed episode", () => {
    const betaPreferred = () =>
        makeBootstrap({
            campaign_preferences: {
                startup_mode: "preferred_campaign",
                preferred_campaign_id: "campaign-b",
                last_visited_campaign_id: null,
            },
        })
    const checkButton = () => screen.getByRole("button", { name: "Check my session" })
    const polite = () => screen.getByRole("status")

    async function unconfirmedBeta() {
        refreshOutcome.unapplied = true
        renderForm()
        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())
        await screen.findByRole("alert")
        refreshOutcome.unapplied = false
    }

    it("A7: editing keeps the notice and its Check my session button", async () => {
        await unconfirmedBeta()
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(checkButton()).toBeInTheDocument()
        fireEvent.click(resumeRadio())
        expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(checkButton()).toBeInTheDocument()
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A8: a matching bootstrap removes the notice and announces once, keeping a newer draft", async () => {
        await unconfirmedBeta()
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        act(() => publish(betaPreferred()))
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(polite()).toHaveTextContent("Startup preference saved.")
        expect(campaignSelect()).toHaveValue("campaign-a")
        expect(saveButton()).toBeEnabled()
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("A8: with the draft still the saved value, the draft is dropped and the saved choice is shown", async () => {
        await unconfirmedBeta()
        act(() => publish(betaPreferred()))
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(polite()).toHaveTextContent("Startup preference saved.")
        expect(campaignSelect()).toHaveValue("campaign-b")
        expect(saveButton()).toBeDisabled()
    })

    it("A8: a bootstrap that does not show the saved value keeps the notice and announces nothing", async () => {
        await unconfirmedBeta()
        act(() => publish(makeBootstrap()))
        expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(polite()).toBeEmptyDOMElement()
    })

    it("A8b: a bootstrap that drops the saved campaign keeps the notice, never names or offers it, and cannot save it", async () => {
        await unconfirmedBeta()
        act(() => publish(makeBootstrap({ campaigns: [alpha] })))
        expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(screen.queryByText(/Beta Campaign/)).not.toBeInTheDocument()
        expect(
            within(campaignSelect())
                .getAllByRole("option")
                .map((option) => option.textContent),
        ).toEqual(["Choose a campaign", "Alpha Campaign"])
        expect(saveButton()).toBeDisabled()
    })

    it("Check my session reads once in place, with a signal, and never reloads or sends the PUT again", async () => {
        await unconfirmedBeta()
        const reads = refreshCalls.length
        const button = checkButton()
        fireEvent.click(button)
        fireEvent.click(button)
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
        expect(refreshCalls.length).toBe(reads + 1)
        expect(refreshCalls.at(-1)).toBeInstanceOf(AbortSignal)
        expect(onCheckSession).not.toHaveBeenCalled()
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
        expect(polite()).toHaveTextContent("Startup preference saved.")
    })

    it("a failed check keeps the notice, the draft and the focus, and says once that it still could not be confirmed", async () => {
        await unconfirmedBeta()
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        refreshOutcome.fail = true
        checkButton().focus()
        fireEvent.click(checkButton())
        await waitFor(() => expect(polite()).toHaveTextContent("still could not be confirmed"))
        expect(checkButton()).toHaveFocus()
        expect(campaignSelect()).toHaveValue("campaign-a")
        expect(screen.getByRole("alert")).toHaveTextContent("could not be confirmed")
        expect(setPreferenceMock).toHaveBeenCalledTimes(1)
    })

    it("moves focus to the checked choice when the check used the button and it still held focus", async () => {
        await unconfirmedBeta()
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        checkButton().focus()
        fireEvent.click(checkButton())
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
        await waitFor(() => expect(fixedRadio()).toHaveFocus())
    })

    it("does not move focus that went elsewhere before the confirmation", async () => {
        await unconfirmedBeta()
        const button = checkButton()
        button.focus()
        fireEvent.click(button)
        campaignSelect().focus()
        fireEvent.blur(button)
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(campaignSelect()).toHaveFocus()
    })

    it("falls back to the next focusable control when the choice itself disappeared", async () => {
        await unconfirmedBeta()
        checkButton().focus()
        fireEvent.click(checkButton())
        // Access to every campaign ended while the check was in flight: the form is replaced by its empty state.
        act(() => publish(makeBootstrap({ campaigns: [] })))
        await waitFor(() => expect(screen.getByRole("link", { name: "Go to campaigns" })).toHaveFocus())
    })
})


// S02-R1: save A is outstanding, the person saves B, and a matching read for A is published while B is pending.
describe("CampaignStartupForm: A is confirmed while a newer save B is pending", () => {
    const EARLIER = "Your earlier startup preference change was confirmed."
    const SAVED = "Startup preference saved."
    const betaPreferred = () =>
        makeBootstrap({
            campaign_preferences: {
                startup_mode: "preferred_campaign",
                preferred_campaign_id: "campaign-b",
                last_visited_campaign_id: null,
            },
        })
    const polite = () => screen.getByRole("status")

    // How many times the live region came to say `phrase` (a change into text that includes it).
    function recordPolite() {
        const region = polite()
        const snapshots: string[] = []
        const observer = new MutationObserver(() => snapshots.push(region.textContent ?? ""))
        observer.observe(region, { childList: true, subtree: true, characterData: true })
        return {
            times: (phrase: string) =>
                snapshots.filter((text, index) => text.includes(phrase) && !(snapshots[index - 1] ?? "").includes(phrase)).length,
            stop: () => observer.disconnect(),
        }
    }

    // A (Beta) is confirmed but unread; the person then saves B (Alpha), whose PUT is held.
    async function bPending(publishMatch = true) {
        refreshOutcome.unapplied = true
        renderForm()
        fireEvent.click(fixedRadio())
        fireEvent.change(campaignSelect(), { target: { value: "campaign-b" } })
        fireEvent.click(saveButton())
        await screen.findByRole("alert")
        let settle!: { ok: () => void; fail: (cause: unknown) => void }
        setPreferenceMock.mockImplementationOnce(
            () =>
                new Promise<void>((resolve, reject) => {
                    settle = {
                        ok: () => {
                            serverPreferred = "campaign-a"
                            resolve()
                        },
                        fail: reject,
                    }
                }),
        )
        fireEvent.change(campaignSelect(), { target: { value: "campaign-a" } })
        fireEvent.click(saveButton())
        await waitFor(() => expect(setPreferenceMock).toHaveBeenCalledTimes(2))
        const heard = recordPolite()
        // The matching read for A arrives while B is pending.
        if (publishMatch) act(() => publish(betaPreferred()))
        return { settle, heard }
    }

    it("exposes A's confirmation at once, once, and never as B's", async () => {
        const { heard } = await bPending()
        expect(polite()).toHaveTextContent(EARLIER)
        expect(polite()).not.toHaveTextContent(SAVED)
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(heard.times(EARLIER)).toBe(1)
        heard.stop()
    })

    it.each([
        ["a 403", () => new UserPreferenceRequestError(403, "no"), "nothing was saved"],
        ["a 404", () => new UserPreferenceRequestError(404, "gone"), "no longer available"],
        ["a 500", () => new UserPreferenceRequestError(500, "boom"), "could not be saved"],
        ["a network failure", () => new TypeError("offline"), "could not be saved"],
    ])("B rejected with %s: B's failure is reported, A's confirmation stays, announced once", async (_name, failure, message) => {
        const { settle, heard } = await bPending()
        await act(async () => settle.fail(failure()))
        expect(await screen.findByRole("alert")).toHaveTextContent(message)
        expect(screen.getByRole("alert")).not.toHaveTextContent("Your preference was saved")
        expect(polite()).toHaveTextContent(EARLIER)
        expect(polite()).not.toHaveTextContent(SAVED)
        expect(heard.times(EARLIER)).toBe(1)
        expect(heard.times(SAVED)).toBe(0)
        expect(setPreferenceMock).toHaveBeenCalledTimes(2)
        heard.stop()
    })

    it("B succeeds and is read back: its own success replaces the earlier text, each announced once", async () => {
        const { settle, heard } = await bPending()
        refreshOutcome.unapplied = false
        await act(async () => settle.ok())
        await waitFor(() => expect(polite()).toHaveTextContent(SAVED))
        expect(polite()).not.toHaveTextContent(EARLIER)
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(heard.times(EARLIER)).toBe(1)
        expect(heard.times(SAVED)).toBe(1)
        expect(campaignSelect()).toHaveValue("campaign-a")
        heard.stop()
    })

    it("B succeeds but its read-back stays outstanding: B's notice, A's confirmation, and no saved claim for B", async () => {
        const { settle, heard } = await bPending()
        await act(async () => settle.ok())
        expect(await screen.findByRole("alert")).toHaveTextContent("Your preference was saved, but the latest settings could not be confirmed")
        expect(polite()).toHaveTextContent(EARLIER)
        expect(polite()).not.toHaveTextContent(SAVED)
        expect(heard.times(EARLIER)).toBe(1)
        expect(heard.times(SAVED)).toBe(0)
        expect(campaignSelect()).toHaveValue("campaign-a")
        expect(setPreferenceMock).toHaveBeenCalledTimes(2)
        heard.stop()
    })

    // F-S02-1: Check my session confirms A while B's pending save keeps every control disabled.
    describe("focus when the form is locked by the pending save", () => {
        const checkButton = () => screen.getByRole("button", { name: "Check my session" })
        const statusRegion = () => screen.getByRole("status")

        it("hands focus to the status region, which says what happened, when nothing else is enabled", async () => {
            const { heard } = await bPending(false)
            expect(campaignSelect()).toBeDisabled()
            expect(fixedRadio()).toBeDisabled()
            expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled()
            refreshOutcome.unapplied = false
            const button = checkButton()
            button.focus()
            fireEvent.click(button)
            await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
            await waitFor(() => expect(statusRegion()).toHaveFocus())
            expect(statusRegion().isConnected).toBe(true)
            expect(statusRegion()).toHaveTextContent(EARLIER)
            // Controls stay disabled while B is pending.
            expect(campaignSelect()).toBeDisabled()
            expect(heard.times(EARLIER)).toBe(1)
            heard.stop()
        })

        it("does not move focus the person moved elsewhere", async () => {
            const { heard } = await bPending(false)
            const elsewhere = document.createElement("button")
            document.body.appendChild(elsewhere)
            refreshOutcome.unapplied = false
            try {
                const button = checkButton()
                button.focus()
                fireEvent.click(button)
                elsewhere.focus()
                fireEvent.blur(button)
                await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
                await new Promise((resolve) => setTimeout(resolve, 20))
                expect(elsewhere).toHaveFocus()
            } finally {
                elsewhere.remove()
                heard.stop()
            }
        })

        it("keeps the focus on the button when the check fails", async () => {
            const { heard } = await bPending(false)
            refreshOutcome.fail = true
            const button = checkButton()
            button.focus()
            fireEvent.click(button)
            await waitFor(() => expect(polite()).toHaveTextContent("still could not be confirmed"))
            expect(button).toHaveFocus()
            heard.stop()
        })
    })
})
