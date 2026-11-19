import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { NULL_PROFILE, RELEASED } from "../../fixtures/publicCharacter"
import { CharacterPublicProfilePanel } from "./CharacterPublicProfilePanel"

const NOISE = /not recorded|unknown|withheld|not released|—|\b0\b/i

describe("CharacterPublicProfilePanel", () => {
    it("shows every released field under a Public profile heading", () => {
        render(<CharacterPublicProfilePanel profile={RELEASED} />)
        expect(screen.getByRole("heading", { level: 2, name: "Public profile" })).toBeInTheDocument()
        for (const text of [
            "Released Elf",
            "Released Medium",
            RELEASED.summary,
            RELEASED.appearance,
            RELEASED.background,
        ]) {
            expect(screen.getByText(text)).toBeInTheDocument()
        }
    })

    it("omits a null field without a placeholder (A5)", () => {
        const { container } = render(
            <CharacterPublicProfilePanel
                profile={{ ...NULL_PROFILE, summary: "Only this.", size: { code: "m", label: "Medium" } }}
            />,
        )
        expect(screen.getByText("Only this.")).toBeInTheDocument()
        expect(screen.getByText("Medium")).toBeInTheDocument()
        expect(screen.queryByText("Species")).toBeNull()
        expect(screen.queryByText("Appearance")).toBeNull()
        expect(screen.queryByText("Background")).toBeNull()
        expect(container.textContent).not.toMatch(NOISE)
    })

    it("shows one neutral line when every field is null (A5)", () => {
        const { container } = render(<CharacterPublicProfilePanel profile={NULL_PROFILE} />)
        expect(screen.getByText("No public details have been shared.")).toBeInTheDocument()
        expect(container.textContent).not.toMatch(NOISE)
    })
})
