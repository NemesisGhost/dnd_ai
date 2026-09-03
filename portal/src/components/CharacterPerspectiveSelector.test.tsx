import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"

const perspectives = [
    {
        character_id: "character-a",
        character_name: "Character A",
    },
    {
        character_id: "character-b",
        character_name: "Character B",
    },
]

describe("CharacterPerspectiveSelector", () => {
    it("displays the selected character with an accessible label", () => {
        render(
            <CharacterPerspectiveSelector
                perspectives={perspectives}
                selectedCharacterId="character-b"
                onSelectCharacter={vi.fn()}
            />,
        )

        const selector = screen.getByRole("combobox", {
            name: "Character perspective",
        })

        expect(selector).toBeEnabled()
        expect(selector).toHaveValue("character-b")

        expect(
            screen.getByRole("option", {
                name: "Character B",
                selected: true,
            }),
        ).toBeInTheDocument()
    })

    it("reports the requested character without changing its own value", () => {
        const onSelectCharacter = vi.fn()

        render(
            <CharacterPerspectiveSelector
                perspectives={perspectives}
                selectedCharacterId="character-a"
                onSelectCharacter={onSelectCharacter}
            />,
        )

        const selector = screen.getByRole("combobox", {
            name: "Character perspective",
        })

        fireEvent.change(selector, {
            target: {
                value: "character-b",
            },
        })

        expect(onSelectCharacter).toHaveBeenCalledTimes(1)
        expect(onSelectCharacter).toHaveBeenCalledWith(
            "character-b",
        )

        expect(selector).toHaveValue("character-a")
    })

    it("disables the selector when no perspectives are available", () => {
        const onSelectCharacter = vi.fn()

        render(
            <CharacterPerspectiveSelector
                perspectives={[]}
                selectedCharacterId={null}
                onSelectCharacter={onSelectCharacter}
            />,
        )

        const selector = screen.getByRole("combobox", {
            name: "Character perspective",
        })

        expect(selector).toBeDisabled()
        expect(selector).toHaveValue("")

        expect(
            screen.getByRole("option", {
                name: "No character perspectives available",
            }),
        ).toBeDisabled()

        expect(screen.getAllByRole("option")).toHaveLength(1)
        expect(onSelectCharacter).not.toHaveBeenCalled()
    })
})