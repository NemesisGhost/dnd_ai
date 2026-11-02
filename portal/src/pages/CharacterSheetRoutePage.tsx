import { Link, useParams } from "react-router"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterManageLinks } from "../components/CharacterManageLinks"
import { CharacterRecordSections } from "../components/characters/CharacterRecordNav"
import { CharacterSheetBoundary } from "../components/CharacterSheetBoundary"
import { useCharactersBackPath } from "../hooks/useCharactersBackPath"
import type { CharacterDetail } from "../types/character"
import { characterKindLabel } from "../utils/characterKind"
import { sectionsOf } from "../utils/characterSections"
import { CharacterPanels } from "./CharacterDetailPage"
import { CharacterSheetPage } from "./CharacterSheetPage"
import PlaceholderPage from "./PlaceholderPage"

// One character's sheet by address: /app/:campaignId/characters/:characterId. It is independent
// of the selected perspective: opening a character here never selects it, never adds it to the
// selector and never grants control. What the person sees is decided by the server for this
// character: the full sheet at the full tier, the summary panels at the summary tier. The
// character's other sections (Details on the World page, Relationships, Inventory, Parties) are one
// navigation row away, each offered only when the character read says the caller may open it, and
// the sheet is requested only when the server offered it.
// The summary tier's view where the sheet would be: no mechanics beyond the audience-safe fields.
function SummaryPanels({ character }: { character: CharacterDetail }) {
    return (
        <section aria-labelledby="character-summary-heading">
            <p className="character-sheet__eyebrow">{characterKindLabel(character.character_kind)}</p>
            <h1 id="character-summary-heading">{character.name}</h1>
            <p className="authoring-note">The full sheet is not available to you.</p>
            <CharacterPanels character={character} />
        </section>
    )
}

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
                            authoring={character.authoring}
                        />
                        <CharacterRecordSections
                            campaignId={campaignId}
                            characterId={characterId}
                            character={character}
                            route="sheet"
                            main={
                                sectionsOf(character).sheet ? (
                                    <CharacterSheetBoundary
                                        campaignId={campaignId}
                                        characterId={characterId}
                                        fallback={() => <SummaryPanels character={character} />}
                                    >
                                        {(sheet) => <CharacterSheetPage sheet={sheet} character={character} />}
                                    </CharacterSheetBoundary>
                                ) : (
                                    <SummaryPanels character={character} />
                                )
                            }
                        />
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
