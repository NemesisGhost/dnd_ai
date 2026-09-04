import { act, renderHook } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
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
        },
        {
            character_id: "character-b",
            character_name: "Character B",
        },
    ],
}

const bootstrap: SessionBootstrap = {
    ...sessionBootstrapFixture,
    user: {
        ...sessionBootstrapFixture.user,
        user_id: "user-a",
    },
    browser_session_id: "session-a",
    selected_campaign_id: "campaign-a",
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
        reload: vi.fn(),
    }
}

describe("useCharacterPerspective", () => {
    it("selects an authorized character and requests a refresh", () => {
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

        expect(session.reload).toHaveBeenCalledTimes(1)

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
})