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
import { CharacterInventoryPanel } from "../components/InventoryPanels"
import { ItemWorkspace } from "../components/items/ItemWorkspace"
import { NpcAuthoringControls } from "../components/NpcAuthoringControls"
import { OrganizationMembers } from "../components/OrganizationMembers"
import { RelationshipsPanel } from "../components/RelationshipsPanel"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
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
export function CampaignWorldDetailPage() {
    const { campaignId, category, entityId } = useParams<{
        campaignId: string
        category: string
        entityId: string
    }>()
    const worldBackPath = useWorldBackPath(campaignId ?? "")

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
                    <>
                        <WorldLocationDetailPage
                            campaignId={campaignId}
                            location={location}
                        />
                        <RelationshipsPanel campaignId={campaignId} entityId={entityId} />
                    </>
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
                    <>
                        <WorldOrganizationDetailPage
                            campaignId={campaignId}
                            organization={organization}
                        />
                        <OrganizationMembers campaignId={campaignId} organizationId={entityId} />
                        <RelationshipsPanel campaignId={campaignId} entityId={entityId} />
                    </>
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
                    <>
                        <WorldReligionDetailPage
                            campaignId={campaignId}
                            religion={religion}
                        />
                        <RelationshipsPanel campaignId={campaignId} entityId={entityId} />
                    </>
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
                <div className="world-detail__layout">
                    <p>
                        <Link to={worldBackPath}>Back to World</Link>
                    </p>
                    <CharacterDetailPage character={character} />
                    <CharacterInventoryPanel campaignId={campaignId} characterId={entityId} />
                    <NpcAuthoringControls campaignId={campaignId} characterId={entityId} />
                    <RelationshipsPanel campaignId={campaignId} entityId={entityId} />
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
