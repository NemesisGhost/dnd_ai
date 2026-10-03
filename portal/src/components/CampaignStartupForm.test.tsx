import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
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
const refreshOutcome: { fail: boolean } = { fail: false }

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

function Harness({ initial }: { initial: SessionBootstrap }) {
    const [bootstrap, setBootstrap] = useState(initial)
    const refresh = async (): Promise<boolean> => {
        if (refreshOutcome.fail) {
            throw new Error("offline")
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
                <CampaignStartupForm bootstrap={bootstrap} onCheckSession={onCheckSession} />
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
    refreshOutcome.fail = false
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
        fireEvent.click(screen.getByRole("button", { name: "Check my session" }))
        expect(onCheckSession).toHaveBeenCalledTimes(1)
    })
})
