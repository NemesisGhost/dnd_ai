import { areaAuthoringPath, dungeonAuthoringPath } from "../../api/dungeonAuthoring"
import { locationAuthoringPath } from "../../api/locationAuthoring"
import type { LocationDetail } from "../../types/world"

// Where editing a place happens: a dungeon and an area have their own editors, every other place
// the location editor. Shared by the reader and the editors' workspace.
export function locationEditPath(campaignId: string, location: LocationDetail): string {
    const root = `/app/${encodeURIComponent(campaignId)}`
    return location.location_type_code === "dungeon"
        ? `${root}/world/dungeon/${encodeURIComponent(location.location_id)}/edit`
        : location.location_type_code === "dungeon_area" && location.parent_location_id !== null
          ? `${root}/world/dungeon/${encodeURIComponent(location.parent_location_id)}/areas/${encodeURIComponent(location.location_id)}/edit`
          : `${root}/world/location/${encodeURIComponent(location.location_id)}/edit`
}

// The authoring read the edit link consults, by kind of place.
export function locationViewPath(campaignId: string, location: LocationDetail): string {
    return location.location_type_code === "dungeon"
        ? dungeonAuthoringPath(campaignId, location.location_id)
        : location.location_type_code === "dungeon_area"
          ? areaAuthoringPath(campaignId, location.location_id)
          : locationAuthoringPath(campaignId, location.location_id)
}

// "dungeon", "dungeon area" or "location", for copy.
export function locationNoun(location: LocationDetail): string {
    return location.location_type_code === "dungeon" || location.location_type_code === "dungeon_area"
        ? location.location_type_code.replace("_", " ")
        : "location"
}
