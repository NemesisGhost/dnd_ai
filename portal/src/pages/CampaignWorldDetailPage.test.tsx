import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { CharacterDetail } from "../types/character"
import type { LocationDetail } from "../types/world"
import { CampaignWorldDetailPage } from "./CampaignWorldDetailPage"

const {
    fetchLocationDetailMock,
    fetchReligionDetailMock,
    fetchItemDetailMock,
    fetchEventDetailMock,
    fetchCharacterMock,
} = vi.hoisted(() => ({
    fetchLocationDetailMock: vi.fn(),
    fetchReligionDetailMock: vi.fn(),
    fetchItemDetailMock: vi.fn(),
    fetchEventDetailMock: vi.fn(),
    fetchCharacterMock: vi.fn(),
}))

vi.mock("../api/world", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/world")>()
    return {
        ...actual,
        fetchLocationDetail: fetchLocationDetailMock,
        fetchReligionDetail: fetchReligionDetailMock,
        fetchItemDetail: fetchItemDetailMock,
        fetchEventDetail: fetchEventDetailMock,
    }
})

vi.mock("../api/character", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/character")>()
    return {
        ...actual,
        fetchCharacter: fetchCharacterMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

const locationFixture: LocationDetail = {
    location_id: "location-a",
    name: "The Sunken Archive",
    summary: null,
    location_type_code: "building",
    parent_location_id: null,
    breadcrumbs: [],
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: null,
    is_destroyed: null,
    alarm_level: null,
    condition_notes: null,
}

const characterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Sella Vane",
    species_code: "human",
    size_category: "medium",
    current_hit_points: null,
    maximum_hit_points: null,
    temporary_hit_points: null,
    exhaustion_level: null,
    death_save_successes: null,
    death_save_failures: null,
    current_location_id: null,
    active_encounter_id: null,
    conditions: null,
    resources: null,
}

function renderAt(path: string) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route
                    path="/app/:campaignId/world/:category/:entityId"
                    element={<CampaignWorldDetailPage />}
                />
                <Route
                    path="/app/:campaignId/world/:category"
                    element={<CampaignWorldDetailPage />}
                />
            </Routes>
        </MemoryRouter>,
    )
}

beforeEach(() => {
    fetchLocationDetailMock.mockReset()
    fetchReligionDetailMock.mockReset()
    fetchItemDetailMock.mockReset()
    fetchEventDetailMock.mockReset()
    fetchCharacterMock.mockReset()
})

describe("CampaignWorldDetailPage", () => {
    it("loads and renders the location detail route", async () => {
        fetchLocationDetailMock.mockResolvedValue(locationFixture)

        renderAt("/app/campaign-a/world/location/location-a")

        await waitFor(() => {
            expect(
                screen.getByRole("heading", {
                    level: 1,
                    name: "The Sunken Archive",
                }),
            ).toBeInTheDocument()
        })

        expect(fetchLocationDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "location-a",
            expect.any(AbortSignal),
        )
    })

    it("loads the audience-safe character detail, never the full character sheet", async () => {
        fetchCharacterMock.mockResolvedValue(characterFixture)

        renderAt("/app/campaign-a/world/character/character-a")

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 1, name: "Sella Vane" }),
            ).toBeInTheDocument()
        })

        expect(fetchCharacterMock).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
            expect.any(AbortSignal),
        )

        expect(
            screen.getByRole("link", { name: "Back to World" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")
    })

    it("fails closed for an unsupported category (organization)", () => {
        renderAt("/app/campaign-a/world/organization/org-a")

        expect(
            screen.getByText("World detail unavailable"),
        ).toBeInTheDocument()

        expect(fetchLocationDetailMock).not.toHaveBeenCalled()
    })

    it("fails closed for an invalid category string", () => {
        renderAt("/app/campaign-a/world/quest/quest-a")

        expect(
            screen.getByText("World detail unavailable"),
        ).toBeInTheDocument()
    })

    it("fails closed when the entity id is missing", () => {
        renderAt("/app/campaign-a/world/location")

        expect(
            screen.getByText("World detail unavailable"),
        ).toBeInTheDocument()

        expect(fetchLocationDetailMock).not.toHaveBeenCalled()
    })
})
