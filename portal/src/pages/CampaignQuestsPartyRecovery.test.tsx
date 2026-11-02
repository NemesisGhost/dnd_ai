import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { QuestRequestError } from "../api/quests"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { AuthorizedParty, SessionBootstrap } from "../types/bootstrap"
import type { CampaignQuestListItem } from "../types/quest"
import { CampaignQuestsPage } from "./CampaignQuestsPage"

const mocks = vi.hoisted(() => ({ fetchCampaignQuests: vi.fn() }))

vi.mock("../api/quests", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/quests")>()),
    fetchCampaignQuests: mocks.fetchCampaignQuests,
}))
vi.mock("../hooks/useAccessOverview", () => ({
    useAccessOverview: () => ({ state: { status: "loading" }, retry: vi.fn() }),
}))

const PARTY: AuthorizedParty = { party_id: "p1", party_name: "The Company" }
const OTHER: AuthorizedParty = { party_id: "p2", party_name: "The Council" }
const THIRD: AuthorizedParty = { party_id: "p3", party_name: "The Guild" }

const PRIVATE: CampaignQuestListItem[] = [{ quest_id: "q-private", name: "Company secret quest", status_code: "active" }]
const OPEN: CampaignQuestListItem[] = [{ quest_id: "q-open", name: "Campaign-wide quest", status_code: "active" }]

function bootstrap(parties: AuthorizedParty[], currentTimeSet = true): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        campaigns: [
            {
                ...sessionBootstrapFixture.campaigns[0]!,
                campaign_id: "c1",
                capabilities: ["campaign.view"],
                current_time_set: currentTimeSet,
                character_perspectives: [{ character_id: "char", character_name: "Aria", authorized_parties: parties }],
            },
        ],
    }
}

interface Deferred<T> {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (error: unknown) => void
}

function deferred<T>(): Deferred<T> {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve, reject }
}

const refresh = vi.fn()
// Stable, like the real session hook's `reload`: a bootstrap replacement must not re-run reads.
const reload = vi.fn()
const probe = { location: "", navigateTo: (to: string): void => void to }

function Probe() {
    const here = useLocation()
    const navigate = useNavigate()
    useEffect(() => {
        probe.location = here.pathname + here.search
        probe.navigateTo = (to) => void navigate(to)
    })
    return null
}

// A real session state that `refresh` replaces, as the session bootstrap hook does.
function Session({ initial, children }: { initial: SessionBootstrap; children: ReactNode }) {
    const [state, setState] = useState<SessionBootstrap>(initial)
    const value = useMemo(
        () => ({
            state: { status: "authenticated" as const, bootstrap: state },
            reload,
            refresh: (signal?: AbortSignal) => {
                void signal
                return (refresh() as Promise<SessionBootstrap | false | Error>).then((next) => {
                    if (next === false) return false
                    if (next instanceof Error) throw next
                    setState(next)
                    return true
                })
            },
        }),
        [state],
    )
    return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

function renderQuests(initial: SessionBootstrap, entry = "/app/c1/quests?character_id=char&party_id=p1") {
    const perspective = { getSelectedCharacterId: () => "char", selectCharacter: vi.fn() }
    return render(
        <Session initial={initial}>
            <CharacterPerspectiveContext.Provider value={perspective}>
                <MemoryRouter initialEntries={[entry]}>
                    <Probe />
                    <Routes>
                        <Route path="/app/:campaignId/quests" element={<CampaignQuestsPage />} />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>
        </Session>,
    )
}

const partyOf = (request: unknown[]) => request[2] as string | null

beforeEach(() => {
    mocks.fetchCampaignQuests.mockReset()
    refresh.mockReset()
    probe.location = ""
})

describe("Quests: a selected party that stops being authorized", () => {
    it("rechecks once, clears only the invalid party from the address, and reads the no-party view once", async () => {
        const gate = deferred<SessionBootstrap>()
        refresh.mockReturnValue(gate.promise)
        mocks.fetchCampaignQuests.mockImplementation((_c: string, _ch: string, party: string | null) =>
            party === "p1" ? Promise.reject(new QuestRequestError(404)) : Promise.resolve(OPEN),
        )
        renderQuests(bootstrap([PARTY, OTHER, THIRD]))

        await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
        // While the recheck is pending: no party-private list, no broadened request, selection untouched.
        expect(screen.queryByText("Company secret quest")).toBeNull()
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(probe.location).toContain("party_id=p1")

        // The clock moved on: the party is no longer authorized (two others are).
        await act(async () => gate.resolve(bootstrap([OTHER, THIRD])))
        expect(await screen.findByRole("link", { name: /Campaign-wide quest/ })).toBeInTheDocument()
        expect(refresh).toHaveBeenCalledTimes(1)
        expect(partyOf(mocks.fetchCampaignQuests.mock.calls.at(-1)!)).toBeNull()
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(2)
        await waitFor(() => expect(probe.location).toBe("/app/c1/quests"))
        // The valid choices remain offered; nothing was invented.
        const select = screen.getByRole("combobox", { name: "Party" })
        expect(select).toHaveValue("")
        expect(screen.getByRole("option", { name: "The Council" })).toBeInTheDocument()
        expect(screen.getByRole("option", { name: "The Guild" })).toBeInTheDocument()
        expect(screen.queryByRole("option", { name: "The Company" })).toBeNull()
    })

    it("falls to the campaign-wide view and says membership is undetermined when the clock is now unset", async () => {
        refresh.mockResolvedValue(bootstrap([], false))
        mocks.fetchCampaignQuests.mockImplementation((_c: string, _ch: string, party: string | null) =>
            party === "p1" ? Promise.reject(new QuestRequestError(404)) : Promise.resolve(OPEN),
        )
        renderQuests(bootstrap([PARTY]))

        expect(await screen.findByRole("link", { name: /Campaign-wide quest/ })).toBeInTheDocument()
        expect(screen.getByRole("option", { name: "Party membership undetermined" })).toBeInTheDocument()
        expect(screen.getByText(/cannot be determined because the campaign time has not been set/)).toBeInTheDocument()
        expect(refresh).toHaveBeenCalledTimes(1)
    })

    it("keeps a genuine not-found, with the party still selected, when it is still authorized", async () => {
        refresh.mockResolvedValue(bootstrap([PARTY]))
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        renderQuests(bootstrap([PARTY]))

        expect(await screen.findByRole("heading", { name: "Quests unavailable" })).toBeInTheDocument()
        expect(refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(probe.location).toContain("party_id=p1")
    })

    it("offers retry, never a fabricated fallback, when the refresh itself fails, and the retry is its own episode", async () => {
        refresh.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(bootstrap([PARTY]))
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        renderQuests(bootstrap([PARTY]))

        expect(await screen.findByRole("heading", { name: "Quest information unavailable" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Quests unavailable" })).toBeNull()
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(probe.location).toContain("party_id=p1")

        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("heading", { name: "Quests unavailable" })).toBeInTheDocument()
        expect(refresh).toHaveBeenCalledTimes(2)
    })

    it("never overwrites a deliberate selection made while the recheck is pending, and keeps the address consistent", async () => {
        const gate = deferred<SessionBootstrap>()
        refresh.mockReturnValue(gate.promise)
        mocks.fetchCampaignQuests.mockImplementation((_c: string, _ch: string, party: string | null) =>
            party === "p1" ? Promise.reject(new QuestRequestError(404)) : Promise.resolve(party === "p2" ? PRIVATE : OPEN),
        )
        renderQuests(bootstrap([PARTY, OTHER, THIRD]))
        await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))

        // The page shows nothing party-scoped while rechecking, so the new choice arrives as an
        // address change (Back/Forward or a link), which is exactly what a stale episode must not undo.
        act(() => probe.navigateTo("/app/c1/quests?character_id=char&party_id=p2"))
        expect(await screen.findByRole("link", { name: /Company secret quest/ })).toBeInTheDocument()
        expect(probe.location).toContain("party_id=p2")

        // The late answer revokes p1 only: the newer choice and its content stay.
        await act(async () => gate.resolve(bootstrap([OTHER, THIRD])))
        expect(screen.getByRole("link", { name: /Company secret quest/ })).toBeInTheDocument()
        expect(probe.location).toContain("party_id=p2")
        expect(refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchCampaignQuests.mock.calls.map(partyOf)).toEqual(["p1", "p2"])
    })
})

describe("Quests: a superseded eligibility refresh", () => {
    it("is not an authoritative snapshot: no fallback, the party stays selected, and Try again is offered", async () => {
        // `false` is what the session hook resolves for a refresh that was superseded or not applied.
        refresh.mockResolvedValue(false)
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        renderQuests(bootstrap([PARTY, OTHER, THIRD]))

        expect(await screen.findByRole("heading", { name: "Quest information unavailable" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(probe.location).toContain("party_id=p1")
        expect(refresh).toHaveBeenCalledTimes(1)
    })
})
