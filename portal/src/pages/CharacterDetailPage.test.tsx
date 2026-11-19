import {
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
} from "vitest"
import type { CharacterDetail } from "../types/character"
import { normalizeCharacterRead } from "../api/character"
import { liveBody, MARKER_FIELDS, publicBody } from "../fixtures/publicCharacter"
import { CharacterDetailPage } from "./CharacterDetailPage"

const fullCharacterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Character A",
    character_kind: "character",
    species_code: "human",
    size_category: "medium",
    current_hit_points: 6,
    maximum_hit_points: 12,
    temporary_hit_points: 0,
    exhaustion_level: 0,
    death_save_successes: 0,
    death_save_failures: 0,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [],
    resources: [],
}

describe("CharacterDetailPage", () => {
    it("renders the character overview without protected details", () => {
        const summaryCharacter: CharacterDetail = {
            ...fullCharacterFixture,
            current_hit_points: 6,
            maximum_hit_points: 12,
            temporary_hit_points: 3,
            exhaustion_level: 2,
            conditions: null,
            resources: null,
        }

        render(
            <CharacterDetailPage
                character={summaryCharacter}
            />,
        )

        expect(
            screen.getByRole("heading", {
                name: "Character A",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Overview",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("human"),
        ).toBeInTheDocument()

        expect(
            screen.getByText("medium"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Additional character details are not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Hit points"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Temporary hit points"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Exhaustion level"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByRole("meter"),
        ).not.toBeInTheDocument()
    })

    it("renders full current-state details including zero values", () => {
        render(
            <CharacterDetailPage
                character={fullCharacterFixture}
            />,
        )

        expect(
            screen.getByRole("heading", {
                name: "Current state",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("meter", {
                name: "Hit points",
            }),
        ).toHaveAttribute("aria-valuenow", "6")

        const temporaryHitPoints =
            screen.getByText(
                "Temporary hit points",
            ).nextElementSibling

        const exhaustionLevel =
            screen.getByText(
                "Exhaustion level",
            ).nextElementSibling

        expect(temporaryHitPoints).toHaveTextContent("0")
        expect(exhaustionLevel).toHaveTextContent("0")

        expect(
            screen.queryByText(
                "Additional character details are not available.",
            ),
        ).not.toBeInTheDocument()
    })

    it("shows a fallback when hit points are not recorded", () => {
        const characterWithoutHitPoints: CharacterDetail = {
            ...fullCharacterFixture,
            current_hit_points: null,
            maximum_hit_points: null,
        }

        render(
            <CharacterDetailPage
                character={characterWithoutHitPoints}
            />,
        )

        const hitPoints =
            screen.getByText(
                "Hit points",
            ).nextElementSibling

        expect(hitPoints).toHaveTextContent("Not recorded")

        expect(
            screen.queryByRole("meter"),
        ).not.toBeInTheDocument()
    })
})
describe("CharacterDetailPage tiers", () => {
    const publicCharacter = normalizeCharacterRead(publicBody({ ...MARKER_FIELDS }))
    const NOISE = /not recorded|additional character details|withheld|not released|\b777\b|MARKER/i

    it("renders only the released profile at the public tier (A4)", () => {
        const { container } = render(<CharacterDetailPage character={publicCharacter} />)
        expect(screen.getByRole("heading", { level: 1, name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(screen.getByText("Released Elf")).toBeInTheDocument()
        expect(screen.getByText("Only this character's public profile is available to you.")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Overview" })).toBeNull()
        expect(container.textContent).not.toMatch(NOISE)
    })

    it("renders the live Overview and the released profile apart at summary (A6)", () => {
        render(<CharacterDetailPage character={normalizeCharacterRead(liveBody("summary"))} />)
        const overview = screen.getByRole("heading", { name: "Overview" }).closest("section") as HTMLElement
        const profile = screen.getByRole("heading", { name: "Public profile" }).closest("section") as HTMLElement
        expect(overview).not.toBe(profile)
        expect(overview).toHaveTextContent("LIVE-SPECIES-MARKER")
        expect(overview).not.toHaveTextContent("Released Elf")
        expect(profile).toHaveTextContent("Released Elf")
        expect(profile).not.toHaveTextContent("LIVE-SPECIES-MARKER")
        // The summary tier's mechanics stay absent, as before.
        expect(screen.queryByRole("heading", { name: "Current state" })).toBeNull()
    })

    it("shows the profile beside the full panels (A8)", () => {
        render(<CharacterDetailPage character={normalizeCharacterRead(liveBody("full"))} />)
        expect(screen.getByRole("heading", { name: "Public profile" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Current state" })).toBeInTheDocument()
        expect(screen.getByText("MARKER-CONDITION")).toBeInTheDocument()
    })

    it.each([
        ["no release", { public_profile: null, sections: { details: true, sheet: false, relationships: true, inventory: false, parties: false, public_profile: false } }],
        ["a section flag without a profile", { public_profile: null }],
        ["a profile with the flag false", { sections: { details: true, sheet: false, relationships: true, inventory: false, parties: false, public_profile: false } }],
    ])("shows nothing about a public profile with %s (A7)", (_label, overrides) => {
        const { container } = render(
            <CharacterDetailPage character={normalizeCharacterRead(liveBody("summary", overrides))} />,
        )
        expect(screen.queryByRole("heading", { name: "Public profile" })).toBeNull()
        expect(container.textContent).not.toMatch(/public profile|withheld|not released|no public details/i)
        expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument()
    })

    it("does not read missing conditions and resources keys as the full tier", () => {
        const body = liveBody("summary") as Record<string, unknown>
        delete body.conditions
        delete body.resources
        render(<CharacterDetailPage character={body as unknown as CharacterDetail} />)
        expect(screen.queryByRole("heading", { name: "Conditions" })).toBeNull()
        expect(screen.getByText("Additional character details are not available.")).toBeInTheDocument()
    })
})
