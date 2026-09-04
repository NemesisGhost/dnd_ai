import { useId } from "react"
import type { CampaignContext } from "../types/bootstrap"

interface CharacterPerspectiveSelectorProps {
    perspectives: CampaignContext["character_perspectives"]
    selectedCharacterId: string | null
    onSelectCharacter: (characterId: string) => void
}

export function CharacterPerspectiveSelector({
    perspectives,
    selectedCharacterId,
    onSelectCharacter,
}: CharacterPerspectiveSelectorProps) {
    const selectId = useId()

    const hasPerspectives = perspectives.length > 0

    return (
        <div className="character-perspective-selector">
            <label htmlFor={selectId}>
                Character perspective
            </label>

            <select
                id={selectId}
                value={selectedCharacterId ?? ""}
                disabled={!hasPerspectives}
                onChange={(event) =>
                    onSelectCharacter(event.currentTarget.value)
                }
            >
                <option value="" disabled>
                    {hasPerspectives
                        ? "Select a character"
                        : "No character perspectives available"}
                </option>

                {perspectives.map((character) => (
                    <option
                        key={character.character_id}
                        value={character.character_id}
                    >
                        {character.character_name}
                    </option>
                ))}
            </select>
        </div>
    )
}