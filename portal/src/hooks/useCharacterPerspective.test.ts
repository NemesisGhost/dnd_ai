import { act, renderHook } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type {
    CampaignContext,
    SessionBootstrap,
} from "../types/bootstrap"
import { useCharacterPerspective } from "./useCharacterPerspective"
import type { UseSessionBootstrapResult } from "./useSessionBootstrap"

const fixtureCampaign = sessionBootstrapFixture.campaigns[0]

if (fixtureCampaign === undefined) {
    throw new Error(
        "The session bootstrap fixture must contain a campaign",
    )
}

const campaign = {
    ...fixtureCampaign,
    campaign_id: "campaign-a",
    selected_character_id: null,
    character_perspectives: [
        {
            character_id: "character-a",
            character_name: "Character A",
            authorized_parties: [],
        },
        {
            character_id: "character-b",
            character_name: "Character B",
            authorized_parties: [],
        },
    ],
} satisfies CampaignContext

const bootstrap: SessionBootstrap = {
    ...sessionBootstrapFixture,
    user: {
        ...sessionBootstrapFixture.user,
        user_id: "user-a",
    },
    browser_session_id: "session-a",
    startup_campaign_id: "campaign-a",
    campaign_preferences: {
      startup_mode: "resume_last_visited",
      preferred_campaign_id: null,
      last_visited_campaign_id: null,
    },
    campaigns: [campaign],
}

function makeSession(
    data: SessionBootstrap = bootstrap,
): UseSessionBootstrapResult {
    return {
        state: {
            status: "authenticated",
            bootstrap: data,
        },
        reload: vi.fn(), refresh: vi.fn(),
    }
}

describe("useCharacterPerspective", () => {
    it("commits an authorized character without reloading or refreshing", () => {
        const session = makeSession()

        const { result } = renderHook(
            useCharacterPerspective,
            { initialProps: session },
        )

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBeNull()

        act(() => {
            result.current.selectCharacter(
                "campaign-a",
                "character-b",
            )
        })

        expect(session.reload).not.toHaveBeenCalled()
        expect(session.refresh).not.toHaveBeenCalled()

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBe("character-b")
    })

    it("ignores unavailable campaigns and characters", () => {
        const session = makeSession()

        const { result } = renderHook(
            useCharacterPerspective,
            { initialProps: session },
        )

        act(() => {
            result.current.selectCharacter(
                "campaign-unavailable",
                "character-b",
            )

            result.current.selectCharacter(
                "campaign-a",
                "character-unavailable",
            )
        })

        expect(session.reload).not.toHaveBeenCalled()

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBeNull()

        expect(
            result.current.getSelectedCharacterId(
                "campaign-unavailable",
            ),
        ).toBeNull()
    })

    it("hides the selection while loading and restores it after refresh", () => {
        const session = makeSession()

        const { result, rerender } = renderHook(
            useCharacterPerspective,
            { initialProps: session },
        )

        act(() => {
            result.current.selectCharacter(
                "campaign-a",
                "character-b",
            )
        })

        rerender({
            state: { status: "loading" },
            reload: session.reload,
            refresh: vi.fn(),
        })

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBeNull()

        rerender(session)

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBe("character-b")
    })

    it("does not return a character removed by a refreshed bootstrap", () => {
        const session = makeSession()

        const { result, rerender } = renderHook(
            useCharacterPerspective,
            { initialProps: session },
        )

        act(() => {
            result.current.selectCharacter(
                "campaign-a",
                "character-b",
            )
        })

        rerender(
            makeSession({
                ...bootstrap,
                campaigns: [
                    {
                        ...campaign,
                        character_perspectives: [],
                    },
                ],
            }),
        )

        expect(
            result.current.getSelectedCharacterId("campaign-a"),
        ).toBeNull()
    })

    it.each(["user", "session"] as const)(
        "does not reuse a selection after the %s changes",
        (changedScope) => {
            const session = makeSession()

            const { result, rerender } = renderHook(
                useCharacterPerspective,
                { initialProps: session },
            )

            act(() => {
                result.current.selectCharacter(
                    "campaign-a",
                    "character-b",
                )
            })

            const changedBootstrap: SessionBootstrap = {
                ...bootstrap,
                user: {
                    ...bootstrap.user,
                    user_id:
                        changedScope === "user"
                            ? "user-b"
                            : bootstrap.user.user_id,
                },
                browser_session_id:
                    changedScope === "session"
                        ? "session-b"
                        : bootstrap.browser_session_id,
            }

            rerender(makeSession(changedBootstrap))

            expect(
                result.current.getSelectedCharacterId("campaign-a"),
            ).toBeNull()
        },
    )

    it("does not apply one campaign's selection to another campaign", () => {
        const session = makeSession({
            ...bootstrap,
            campaigns: [
                campaign,
                {
                    ...campaign,
                    campaign_id: "campaign-b",
                },
            ],
        })

        const { result } = renderHook(
            useCharacterPerspective,
            { initialProps: session },
        )

        act(() => {
            result.current.selectCharacter(
                "campaign-a",
                "character-b",
            )
        })

        expect(
            result.current.getSelectedCharacterId("campaign-b"),
        ).toBeNull()
    })

    it("clears the character without restoring the server default", () => {
        const session = makeSession({
            ...bootstrap,
            campaigns: [
                {
                    ...campaign,
                    selected_character_id: "character-a",
                },
            ],
        })

        const { result } = renderHook(
            useCharacterPerspective,
            {
                initialProps: session,
            },
        )

        expect(
            result.current.getSelectedCharacterId(
                "campaign-a",
            ),
        ).toBe("character-a")

        act(() => {
            result.current.selectCharacter(
                "campaign-a",
                null,
            )
        })

        expect(session.reload).not.toHaveBeenCalled()
        expect(session.refresh).not.toHaveBeenCalled()

        expect(
            result.current.getSelectedCharacterId(
                "campaign-a",
            ),
        ).toBeNull()
    })

    describe("syncCharacterFromUrl", () => {
        it("updates the visible selection for an authorized character without reloading", () => {
            const session = makeSession()

            const { result } = renderHook(
                useCharacterPerspective,
                { initialProps: session },
            )

            act(() => {
                result.current.syncCharacterFromUrl(
                    "campaign-a",
                    "character-b",
                )
            })

            expect(
                result.current.getSelectedCharacterId("campaign-a"),
            ).toBe("character-b")

            expect(session.reload).not.toHaveBeenCalled()
        })

        it("ignores a character not in the campaign's authorized character_perspectives", () => {
            const session = makeSession()

            const { result } = renderHook(
                useCharacterPerspective,
                { initialProps: session },
            )

            act(() => {
                result.current.syncCharacterFromUrl(
                    "campaign-a",
                    "character-unauthorized",
                )
            })

            expect(
                result.current.getSelectedCharacterId("campaign-a"),
            ).toBeNull()

            expect(session.reload).not.toHaveBeenCalled()
        })

        it("ignores an unavailable campaign", () => {
            const session = makeSession()

            const { result } = renderHook(
                useCharacterPerspective,
                { initialProps: session },
            )

            act(() => {
                result.current.syncCharacterFromUrl(
                    "campaign-unavailable",
                    "character-b",
                )
            })

            expect(session.reload).not.toHaveBeenCalled()

            expect(
                result.current.getSelectedCharacterId(
                    "campaign-unavailable",
                ),
            ).toBeNull()
        })
    })
})
describe("useCharacterPerspective over the selected-context store (P02-3)", () => {
    const other = { ...campaign, campaign_id: "campaign-b", selected_character_id: "character-x", character_perspectives: [
        { character_id: "character-x", character_name: "X", authorized_parties: [] },
    ] } satisfies CampaignContext
    const two: SessionBootstrap = { ...bootstrap, campaigns: [campaign, other] }

    it("never reads a perspective chosen under another campaign", () => {
        const { result } = renderHook(useCharacterPerspective, { initialProps: makeSession(two) })
        act(() => result.current.selectCharacter("campaign-a", "character-b"))
        expect(result.current.getSelectedCharacterId("campaign-a")).toBe("character-b")
        expect(result.current.getSelectedCharacterId("campaign-b")).toBe("character-x")
    })

    it("adopting the route campaign replaces another campaign's selection and leaves the new one uninitialized", () => {
        const { result } = renderHook(useCharacterPerspective, { initialProps: makeSession(two) })
        act(() => result.current.selectCharacter("campaign-a", "character-b"))
        act(() => result.current.adoptRouteCampaign("campaign-b"))
        // The server default of campaign-b applies; campaign-a's choice is gone, not parked.
        expect(result.current.getSelectedCharacterId("campaign-b")).toBe("character-x")
        expect(result.current.getSelectedCharacterId("campaign-a")).toBeNull()
        act(() => result.current.adoptRouteCampaign("campaign-a"))
        expect(result.current.getSelectedCharacterId("campaign-a")).toBeNull()
    })

    it("adopting the same campaign keeps its choice, including an explicit none", () => {
        const { result } = renderHook(useCharacterPerspective, { initialProps: makeSession(two) })
        act(() => result.current.selectCharacter("campaign-b", null))
        act(() => result.current.adoptRouteCampaign("campaign-b"))
        expect(result.current.getSelectedCharacterId("campaign-b")).toBeNull()
        act(() => result.current.selectCharacter("campaign-a", "character-a"))
        act(() => result.current.adoptRouteCampaign("campaign-a"))
        expect(result.current.getSelectedCharacterId("campaign-a")).toBe("character-a")
    })

    it("adopts nothing for a campaign the bootstrap does not list or without an authenticated session", () => {
        const { result } = renderHook(useCharacterPerspective, { initialProps: makeSession(two) })
        act(() => result.current.selectCharacter("campaign-a", "character-b"))
        act(() => result.current.adoptRouteCampaign("ghost"))
        expect(result.current.getSelectedCharacterId("campaign-a")).toBe("character-b")

        const loading = renderHook(useCharacterPerspective, {
            initialProps: { state: { status: "loading" }, reload: vi.fn(), refresh: vi.fn() } as UseSessionBootstrapResult,
        })
        act(() => loading.result.current.adoptRouteCampaign("campaign-a"))
        expect(loading.result.current.getSelectedCharacterId("campaign-a")).toBeNull()
    })

    it("does not hand a perspective to a different user or browser session", () => {
        const { result, rerender } = renderHook(useCharacterPerspective, { initialProps: makeSession(two) })
        act(() => result.current.selectCharacter("campaign-a", "character-b"))
        rerender(makeSession({ ...two, browser_session_id: "session-b" }))
        expect(result.current.getSelectedCharacterId("campaign-a")).toBeNull()
    })
})
