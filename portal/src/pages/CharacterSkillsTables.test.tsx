import { act, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { CharacterSkillsTables } from "./CharacterSkillsTables"

const originalObserver = globalThis.ResizeObserver
afterEach(() => { globalThis.ResizeObserver = originalObserver })

function fixtureSkills() {
    return Array.from({ length: 7 }, (_, index) => ({
        ...characterSheetFixture.skills[0], skill_id: `skill-${index}`, display_name: `Skill ${index}`,
    }))
}

describe("CharacterSkillsTables", () => {
    it("renders one semantic table when ResizeObserver is unavailable", () => {
        // @ts-expect-error Exercise browsers without ResizeObserver.
        globalThis.ResizeObserver = undefined
        render(<CharacterSkillsTables skills={fixtureSkills()} />)
        const table = screen.getByRole("table", { name: "Skills" })
        expect(within(table).getAllByRole("columnheader")).toHaveLength(5)
        expect(within(table).getAllByRole("row")).toHaveLength(8)
    })

    it.each([[500, 1], [1300, 2], [1900, 3]])(
        "uses container width %i for %i tables", (width, count) => {
            let callback: ResizeObserverCallback = () => {}
            const disconnect = vi.fn()
            globalThis.ResizeObserver = class {
                constructor(cb: ResizeObserverCallback) { callback = cb }
                observe() {}
                disconnect() { disconnect() }
                unobserve() {}
            }
            const { unmount } = render(<CharacterSkillsTables skills={fixtureSkills()} />)
            act(() => callback([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver))
            const tables = screen.getAllByRole("table")
            expect(tables).toHaveLength(count)
            expect(tables.map((table) => table.getAttribute("aria-label") ?? table.querySelector("caption")?.textContent))
                .toEqual(count === 1 ? ["Skills"] : Array.from({ length: count }, (_, i) => `Skills, part ${i + 1} of ${count}`))
            for (const table of tables) expect(within(table).getAllByRole("columnheader")).toHaveLength(5)
            expect(tables.flatMap((table) => within(table).getAllByRole("row").slice(1).map((row) => row.querySelector("td")?.textContent)))
                .toEqual(fixtureSkills().map((skill) => skill.display_name))
            unmount()
            expect(disconnect).toHaveBeenCalledOnce()
        },
    )

    it("shows a checked, disabled checkbox labeled Proficient for a proficient skill", () => {
        render(<CharacterSkillsTables skills={[characterSheetFixture.skills[0]]} />)
        const checkbox = screen.getByRole("checkbox", { name: "Proficient" })
        expect(checkbox).toBeChecked()
        expect(checkbox).toBeDisabled()
        expect(screen.queryByText("×2")).not.toBeInTheDocument()
    })

    it("shows a checked checkbox labeled Expertise with a ×2 mark for an expertise skill", () => {
        const skill = { ...characterSheetFixture.skills[0], is_proficient: true, is_expertise: true }
        render(<CharacterSkillsTables skills={[skill]} />)
        const checkbox = screen.getByRole("checkbox", { name: "Expertise" })
        expect(checkbox).toBeChecked()
        expect(screen.getByText("×2")).toBeInTheDocument()
    })

    it("shows an unchecked checkbox labeled Not proficient without a ×2 mark", () => {
        const skill = { ...characterSheetFixture.skills[0], is_proficient: false, is_expertise: false }
        render(<CharacterSkillsTables skills={[skill]} />)
        const checkbox = screen.getByRole("checkbox", { name: "Not proficient" })
        expect(checkbox).not.toBeChecked()
        expect(screen.queryByText("×2")).not.toBeInTheDocument()
    })
})
