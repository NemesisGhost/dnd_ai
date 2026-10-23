import { Link, useParams } from "react-router"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterManageLinks } from "../components/CharacterManageLinks"
import { CharacterRelationshipsSection } from "../components/CharacterRelationshipsSection"
import { CharacterSheetBoundary } from "../components/CharacterSheetBoundary"
import { useCharactersBackPath } from "../hooks/useCharactersBackPath"
import { characterKindLabel } from "../utils/characterKind"
import { CharacterPanels } from "./CharacterDetailPage"
import { CharacterSheetPage } from "./CharacterSheetPage"
import PlaceholderPage from "./PlaceholderPage"

// One character's sheet by address: /app/:campaignId/characters/:characterId. It is independent
// of the selected perspective: opening a character here never selects it, never adds it to the
// selector and never grants control. What the person sees is decided by the server for this
// character: the full sheet at the full tier, the summary panels at the summary tier. A reader
// (no canon.edit) also gets the read-only Relationships section below either one.
function CharacterSheetRoute({ campaignId, characterId }: { campaignId: string; characterId: string }) {
    const back = useCharactersBackPath(campaignId)
    return (
        <div className="character-sheet-route">
            <p className="authoring-page__breadcrumb">
                <Link to={back}>Back to characters</Link>
            </p>
            <CharacterBoundary campaignId={campaignId} characterId={characterId}>
                {(character) => (
                    <>
                        <CharacterManageLinks
                            campaignId={campaignId}
                            characterId={characterId}
                            kind={character.character_kind}
                        />
                        <CharacterSheetBoundary
                            campaignId={campaignId}
                            characterId={characterId}
                            fallback={() => (
                                <section aria-labelledby="character-summary-heading">
                                    <p className="character-sheet__eyebrow">
                                        {characterKindLabel(character.character_kind)}
                                    </p>
                                    <h1 id="character-summary-heading">{character.name}</h1>
                                    <p className="authoring-note">The full sheet is not available to you.</p>
                                    <CharacterPanels character={character} />
                                </section>
                            )}
                        >
                            {(sheet) => <CharacterSheetPage sheet={sheet} character={character} />}
                        </CharacterSheetBoundary>
                        <CharacterRelationshipsSection campaignId={campaignId} characterId={characterId} />
                    </>
                )}
            </CharacterBoundary>
        </div>
    )
}

export function CharacterSheetRoutePage() {
    const { campaignId, characterId } = useParams<{ campaignId: string; characterId: string }>()
    if (campaignId === undefined || characterId === undefined) {
        return (
            <PlaceholderPage
                title="Character unavailable"
                description="The requested character information is not available."
            />
        )
    }
    return <CharacterSheetRoute key={`${campaignId}:${characterId}`} campaignId={campaignId} characterId={characterId} />
}
