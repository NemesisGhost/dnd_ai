import {
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    RouterProvider,
    Routes,
    createMemoryRouter,
    useLocation,
} from "react-router"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { CampaignCharactersBrowsePage, CampaignCharactersPage } from "./CampaignCharactersPage"

const {
    canEditMock,
    characterRetryMock,
    characterSheetRetryMock,
    getSelectedCharacterIdMock,
    useCharacterMock,
    useCharacterSheetMock,
} = vi.hoisted(() => ({
    canEditMock: vi.fn(() => false),
    characterRetryMock: vi.fn(),
    characterSheetRetryMock: vi.fn(),
    getSelectedCharacterIdMock: vi.fn(),
    useCharacterMock: vi.fn(),
    useCharacterSheetMock: vi.fn(),
}))

vi.mock(
    "../context/CharacterPerspectiveContext",
    () => ({
        usePerspective: () => ({
            getSelectedCharacterId:
                getSelectedCharacterIdMock,
        }),
    }),
)

vi.mock("../hooks/useCampaignCapability", () => ({
    useCampaignCapability: () => canEditMock(),
}))

vi.mock("../components/CharactersBrowser", () => ({
    CharactersBrowser: ({ campaignId }: { campaignId: string }) => (
        <p>Browser for {campaignId}</p>
    ),
}))

vi.mock("../hooks/useCharacter", () => ({
    useCharacter: useCharacterMock,
}))

vi.mock("../hooks/useCharacterSheet", () => ({
    useCharacterSheet: useCharacterSheetMock,
}))

function renderAt(
    initialPath: string,
    routePath: string,
) {
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route
                    path={routePath}
                    element={
                        routePath.endsWith("/all")
                            ? <CampaignCharactersBrowsePage />
                            : <CampaignCharactersPage />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

beforeEach(() => {
    canEditMock.mockReset()
    canEditMock.mockReturnValue(false)
    characterRetryMock.mockReset()
    characterSheetRetryMock.mockReset()
    getSelectedCharacterIdMock.mockReset()
    useCharacterMock.mockReset()
    useCharacterSheetMock.mockReset()
})

describe("CampaignCharactersPage", () => {
    it("fails closed when there is no campaign route parameter", () => {
        renderAt("/standalone", "/standalone")

        expect(
            screen.getByRole("heading", {
                name: "Character unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            getSelectedCharacterIdMock,
        ).not.toHaveBeenCalled()

        expect(
            useCharacterMock,
        ).not.toHaveBeenCalled()

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()
    })

    it("shows the character browser, not an empty placeholder, when no perspective is selected", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(screen.getByText("Browser for campaign-a")).toBeInTheDocument()
        expect(screen.queryByText("No character selected")).not.toBeInTheDocument()
        // Only the browser link: there is no selected character to go back to.
        expect(screen.queryByRole("link", { name: "Selected character" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/all",
        )

        expect(
            getSelectedCharacterIdMock,
        ).toHaveBeenCalledWith("campaign-a")

        expect(
            useCharacterMock,
        ).not.toHaveBeenCalled()

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()
    })

    it("replaces the index with the selected character's record, carrying the entry's state", () => {
        getSelectedCharacterIdMock.mockReturnValue("character-a")
        const task = { v: 1, root: "characters", scope: { campaignId: "campaign-a" }, trail: [] }
        const router = createMemoryRouter(
            [
                { path: "/app/:campaignId/characters", element: <CampaignCharactersPage /> },
                { path: "/app/:campaignId/characters/:characterId", element: <RecordProbe /> },
            ],
            { initialEntries: [{ pathname: "/app/campaign-a/characters", state: { task } }] },
        )
        render(<RouterProvider router={router} />)

        expect(screen.getByTestId("record")).toHaveTextContent("/app/campaign-a/characters/character-a")
        // A REPLACE: the index is not left behind in history, so Back does not bounce through it.
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.state).toEqual({ task })
        // The index itself reads nothing: the record page owns the character and sheet requests.
        expect(useCharacterMock).not.toHaveBeenCalled()
        expect(useCharacterSheetMock).not.toHaveBeenCalled()
    })

    it("offers New PC to editors only, carrying the view to return to", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)
        canEditMock.mockReturnValue(true)

        renderAt("/app/campaign-a/characters", "/app/:campaignId/characters")

        expect(screen.getByRole("link", { name: "New PC" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/pc/new",
        )
        expect(screen.queryByRole("link", { name: "New character" })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "New NPC" })).not.toBeInTheDocument()
    })

    it("hides New PC without canon.edit", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)

        renderAt("/app/campaign-a/characters", "/app/:campaignId/characters")

        expect(screen.queryByRole("link", { name: "New PC" })).not.toBeInTheDocument()
    })

    it("shows the browser at /characters/all even with a perspective, linking to the record as a new task", () => {
        getSelectedCharacterIdMock.mockReturnValue("character-a")

        renderAt("/app/campaign-a/characters/all", "/app/:campaignId/characters/all")

        expect(screen.getByText("Browser for campaign-a")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        // The selected character is one link away, straight to its record (not through the index).
        expect(screen.getByRole("link", { name: "Selected character" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/character-a",
        )
        // Browsing requests no character data.
        expect(useCharacterMock).not.toHaveBeenCalled()
    })
})

function RecordProbe() {
    return <p data-testid="record">{useLocation().pathname}</p>
}
