import type { ReactNode } from "react"
import { Link, Navigate, useLocation, useParams } from "react-router"
import { CharactersCreateAction } from "../components/characters/CharactersCreateAction"
import { CharactersBrowser } from "../components/CharactersBrowser"
import { ArrivalHeadingFocus } from "../navigation/ArrivalHeadingFocus"
import { navTaskState } from "../navigation/navStart"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import PlaceholderPage from "./PlaceholderPage"

// The Characters page header: local navigation between the selected character's sheet and the
// list of every character the person may see, and the create action. The create offer uses the
// same rule as the World's creation links: canon.edit from the bootstrap decides what to show, the
// server re-checks every request, and it is independent of the selected character, so it is also
// there with none selected. New character opens the existing NPC / player-character chooser, which
// carries the Characters view on to either form.
function CharactersHeader({
    campaignId,
    selectedCharacterId,
}: {
    campaignId: string
    selectedCharacterId: string | null
}) {
    const { pathname } = useLocation()
    const base = `/app/${encodeURIComponent(campaignId)}/characters`
    const browsing = pathname.replace(/\/+$/, "") === `${base}/all`
    return (
        <header className="characters-page__header">
            <nav aria-label="Characters views" className="characters-page__views">
                {selectedCharacterId !== null ? (
                    <Link
                        to={`${base}/${encodeURIComponent(selectedCharacterId)}`}
                        state={navTaskState(`${base}/${encodeURIComponent(selectedCharacterId)}`, "characters")}
                        className="characters-page__view-link"
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
            <CharactersCreateAction campaignId={campaignId} />
        </header>
    )
}

function WithCharactersHeader({
    campaignId,
    selectedCharacterId,
    children,
}: {
    campaignId: string
    selectedCharacterId: string | null
    children: ReactNode
}) {
    return (
        <>
            <CharactersHeader campaignId={campaignId} selectedCharacterId={selectedCharacterId} />
            {children}
        </>
    )
}

// /app/:campaignId/characters. With a selected perspective it is a REPLACE to that character's record
// (`/characters/:id`, the sheet and the same section row as every other entry; docs/UI_DESIGN.md §5.5,
// decision PD-4): the index is never a second rendering of the sheet, and Back does not return to it. The
// entry's state (its task and context mirror) is carried over, so the record opens in the task that
// reached the index. With no perspective (typically a GM, or a player who can only view characters) it is
// the character browser instead of an empty placeholder.
export function CampaignCharactersPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()
    const { state } = useLocation()

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

    if (characterId !== null) {
        return (
            <Navigate
                replace
                to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}`}
                state={state}
            />
        )
    }

    return (
        <WithCharactersHeader campaignId={campaignId} selectedCharacterId={null}>
            <h1>Characters</h1>
            <CharactersBrowser campaignId={campaignId} />
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
            selectedCharacterId={getSelectedCharacterId(campaignId)}
        >
            <h1>Characters</h1>
            <ArrivalHeadingFocus />
            <CharactersBrowser campaignId={campaignId} />
        </WithCharactersHeader>
    )
}
