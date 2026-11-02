import { Link, useParams } from "react-router"
import { useWorldBackPath } from "../hooks/useWorldBackPath"
import {
    fetchEventDetail,
    fetchItemDetail,
    fetchLocationDetail,
    fetchOrganizationDetail,
    fetchReligionDetail,
} from "../api/world"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterRecordSections } from "../components/characters/CharacterRecordNav"
import { ItemWorkspace } from "../components/items/ItemWorkspace"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { WorldRecordWorkspace } from "../components/world/WorldRecordWorkspace"
import { WorldEntityDetailBoundary } from "../components/WorldEntityDetailBoundary"
import { isWorldDetailCategory } from "../types/world"
import { CharacterDetailPage } from "./CharacterDetailPage"
import PlaceholderPage from "./PlaceholderPage"
import { WorldEventDetailPage } from "./WorldEventDetailPage"
import { WorldItemDetailPage } from "./WorldItemDetailPage"
import { WorldLocationDetailPage } from "./WorldLocationDetailPage"
import { WorldOrganizationDetailPage } from "./WorldOrganizationDetailPage"
import { WorldReligionDetailPage } from "./WorldReligionDetailPage"

// Route-based World detail dispatcher (UI_DESIGN.md §5.4,
// UI_STYLE_GUIDE.md §10.2): /app/:campaignId/world/:category/:entityId.
// `category` is validated against the categories with an independently
// loadable detail contract and fails closed for anything else (including
// "relationship", which has none until Phase 15.2).
//
// People who can edit canon get a guided workspace for the records that go through the canon
// lifecycle (places, dungeons, areas, organizations, religions, NPCs and player characters; an
// item gets the item workspace). Everyone else, and an event for everyone, gets the read-only page
// below, which sends no authoring, lifecycle or sources request.
export function CampaignWorldDetailPage() {
    const { campaignId, category, entityId } = useParams<{
        campaignId: string
        category: string
        entityId: string
    }>()
    const worldBackPath = useWorldBackPath(campaignId ?? "")
    const canEdit = useCampaignCapability(campaignId ?? "", "canon.edit")

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

    if (canEdit && (category === "location" || category === "organization" || category === "religion" || category === "character")) {
        return <WorldRecordWorkspace key={`${category}:${entityId}`} campaignId={campaignId} category={category} entityId={entityId} />
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

    if (category === "organization") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchOrganizationDetail}
                resourceLabel="organization"
            >
                {(organization) => (
                    <WorldOrganizationDetailPage
                        campaignId={campaignId}
                        organization={organization}
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
        return <WorldItemEntry campaignId={campaignId} entityId={entityId} />
    }

    if (category === "event") {
        return (
            <WorldEntityDetailBoundary
                campaignId={campaignId}
                entityId={entityId}
                fetchDetail={fetchEventDetail}
                resourceLabel="event"
                lifecycle={false}
            >
                {(event) => (
                    <>
                        <WorldEventDetailPage
                            campaignId={campaignId}
                            event={event}
                        />
                        {canEdit ? (
                            <p>
                                <Link to={`/app/${encodeURIComponent(campaignId)}/events/${encodeURIComponent(entityId)}`}>
                                    Open the event record
                                </Link>
                            </p>
                        ) : null}
                    </>
                )}
            </WorldEntityDetailBoundary>
        )
    }

    // category === "character": the audience-safe Character Detail
    // response, never the full Character Sheet — a World card is not the
    // selected player-character perspective (UI_STYLE_GUIDE.md §10.2). The same record navigation
    // as the Characters page offers the sheet, relationships, inventory and parties this caller may
    // open.
    return (
        <CharacterBoundary campaignId={campaignId} characterId={entityId}>
            {(character) => (
                <div className="world-detail__layout">
                    <p>
                        <Link to={worldBackPath}>Back to World</Link>
                    </p>
                    <CharacterRecordSections
                        campaignId={campaignId}
                        characterId={entityId}
                        character={character}
                        route="world"
                        main={<CharacterDetailPage character={character} />}
                    />
                </div>
            )}
        </CharacterBoundary>
    )
}

// An item on the World page. People who can edit canon get the item workspace (the same page as
// from the item inventory, returning to the World browser); everyone else gets the reader, which
// shows only what the World API allows them. Players send no authoring request.
function WorldItemEntry({ campaignId, entityId }: { campaignId: string; entityId: string }) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    if (canEdit) {
        return <ItemWorkspace key={entityId} campaignId={campaignId} itemId={entityId} origin="world" />
    }
    return (
        <WorldEntityDetailBoundary
            campaignId={campaignId}
            entityId={entityId}
            fetchDetail={fetchItemDetail}
            resourceLabel="item"
            lifecycle={false}
        >
            {(item) => <WorldItemDetailPage campaignId={campaignId} item={item} />}
        </WorldEntityDetailBoundary>
    )
}
