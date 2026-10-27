import type { ReactNode } from "react"
import { Link, useLocation, useParams } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterSheetBoundary } from "../components/CharacterSheetBoundary"
import { CharactersBrowser } from "../components/CharactersBrowser"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { CharacterSheetPage } from "./CharacterSheetPage"
import PlaceholderPage from "./PlaceholderPage"

// The Characters page header: local navigation between the selected character's sheet and the
// list of every character the person may see, and the create action. The create offer uses the
// same rule as the World's creation links: canon.edit from the bootstrap decides what to show, the
// server re-checks every request, and it is independent of the selected character, so it is also
// there with none selected. New PC opens player-character creation directly; NPCs are created from
// the World's People category.
function CharactersHeader({
    campaignId,
    hasSelection,
}: {
    campaignId: string
    hasSelection: boolean
}) {
    const canCreate = useCampaignCapability(campaignId, "canon.edit")
    const { pathname, search } = useLocation()
    const base = `/app/${encodeURIComponent(campaignId)}/characters`
    const browsing = pathname.replace(/\/+$/, "") === `${base}/all`
    return (
        <header className="characters-page__header">
            <nav aria-label="Characters views" className="characters-page__views">
                {hasSelection ? (
                    <Link
                        to={base}
                        className="characters-page__view-link"
                        aria-current={browsing ? undefined : "page"}
                    >
                        Selected character
                    </Link>
                ) : null}
                <Link
                    to={`${base}/all`}
                    className="characters-page__view-link"
                    aria-current={browsing ? "page" : undefined}
                >
                    All characters
                </Link>
            </nav>
            {canCreate ? (
                <nav aria-label="Create character" className="authoring-page__actions-row">
                    <Link
                        to={`${base}/pc/new`}
                        state={{ charactersReturn: `${pathname}${search}` }}
                        className="authoring-button"
                    >
                        New PC
                    </Link>
                </nav>
            ) : null}
        </header>
    )
}

function WithCharactersHeader({
    campaignId,
    hasSelection,
    children,
}: {
    campaignId: string
    hasSelection: boolean
    children: ReactNode
}) {
    return (
        <>
            <CharactersHeader campaignId={campaignId} hasSelection={hasSelection} />
            {children}
        </>
    )
}

// /app/:campaignId/characters. The selected perspective's sheet, exactly as before. With no
// perspective (typically a GM, or a player who can only view characters) it is the character
// browser instead of an empty placeholder.
export function CampaignCharactersPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    const { getSelectedCharacterId } =
        usePerspective()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Character unavailable"
                description="The requested character information is not available."
            />
        )
    }

    const characterId =
        getSelectedCharacterId(campaignId)

    if (characterId === null) {
        return (
            <WithCharactersHeader campaignId={campaignId} hasSelection={false}>
                <h1>Characters</h1>
                <CharactersBrowser campaignId={campaignId} />
            </WithCharactersHeader>
        )
    }

    return (
        <WithCharactersHeader campaignId={campaignId} hasSelection>
            <CharacterBoundary
                campaignId={campaignId}
                characterId={characterId}
            >
                {(character) => (
                    <CharacterSheetBoundary
                        campaignId={campaignId}
                        characterId={characterId}
                    >
                        {(sheet) => (
                            <CharacterSheetPage
                                sheet={sheet}
                                character={character}
                            />
                        )}
                    </CharacterSheetBoundary>
                )}
            </CharacterBoundary>
        </WithCharactersHeader>
    )
}

// /app/:campaignId/characters/all. The browser, whether or not a perspective is selected.
export function CampaignCharactersBrowsePage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()
    const { getSelectedCharacterId } =
        usePerspective()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Characters unavailable"
                description="The requested character information is not available."
            />
        )
    }

    return (
        <WithCharactersHeader
            campaignId={campaignId}
            hasSelection={getSelectedCharacterId(campaignId) !== null}
        >
            <h1>Characters</h1>
            <CharactersBrowser campaignId={campaignId} />
        </WithCharactersHeader>
    )
}
