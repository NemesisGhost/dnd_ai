import { Link, useParams } from "react-router"
import {
    fetchEventDetail,
    fetchItemDetail,
    fetchLocationDetail,
    fetchReligionDetail,
} from "../api/world"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { WorldEntityDetailBoundary } from "../components/WorldEntityDetailBoundary"
import { isWorldDetailCategory } from "../types/world"
import { CharacterDetailPage } from "./CharacterDetailPage"
import PlaceholderPage from "./PlaceholderPage"
import { WorldEventDetailPage } from "./WorldEventDetailPage"
import { WorldItemDetailPage } from "./WorldItemDetailPage"
import { WorldLocationDetailPage } from "./WorldLocationDetailPage"
import { WorldReligionDetailPage } from "./WorldReligionDetailPage"

// Route-based World detail dispatcher (UI_DESIGN.md §5.4,
// UI_STYLE_GUIDE.md §10.2): /app/:campaignId/world/:category/:entityId.
// `category` is validated against the categories with an independently
// loadable detail contract and fails closed for anything else (including
// "organization" and "relationship", which have none in this increment —
// see docs/PHASE13D_BACKEND_READINESS.md §10.1/§10.8).
export function CampaignWorldDetailPage() {
    const { campaignId, category, entityId } = useParams<{
        campaignId: string
        category: string
        entityId: string
    }>()

    if (
        campaignId === undefined ||
        category === undefined ||
        entityId === undefined ||
        !isWorldDetailCategory(category)
    ) {
        return (
            <PlaceholderPage
                title="World detail unavailable"
                description="The requested world information is not available."
            />
        )
    }

    if (category === "location") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchLocationDetail}
                resourceLabel="location"
            >
                {(location) => (
                    <WorldLocationDetailPage
                        campaignId={campaignId}
                        location={location}
                    />
                )}
            </WorldEntityDetailBoundary>
        )
    }

    if (category === "religion") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchReligionDetail}
                resourceLabel="religion"
            >
                {(religion) => (
                    <WorldReligionDetailPage
                        campaignId={campaignId}
                        religion={religion}
                    />
                )}
            </WorldEntityDetailBoundary>
        )
    }

    if (category === "item") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchItemDetail}
                resourceLabel="item"
            >
                {(item) => (
                    <WorldItemDetailPage
                        campaignId={campaignId}
                        item={item}
                    />
                )}
            </WorldEntityDetailBoundary>
        )
    }

    if (category === "event") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchEventDetail}
                resourceLabel="event"
            >
                {(event) => (
                    <WorldEventDetailPage
                        campaignId={campaignId}
                        event={event}
                    />
                )}
            </WorldEntityDetailBoundary>
        )
    }

    // category === "character": the audience-safe Character Detail
    // response, never the full Character Sheet — a World card is not the
    // selected player-character perspective (UI_STYLE_GUIDE.md §10.2).
    return (
        <CharacterBoundary campaignId={campaignId} characterId={entityId}>
            {(character) => (
                <div>
                    <p>
                        <Link
                            to={`/app/${encodeURIComponent(campaignId)}/world`}
                        >
                            Back to World
                        </Link>
                    </p>
                    <CharacterDetailPage character={character} />
                </div>
            )}
        </CharacterBoundary>
    )
}
