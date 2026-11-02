import type { DungeonAuthoringView } from "../../types/dungeonAuthoring"
import { areaTally } from "./areaText"

// For the dungeon's Review: where its areas stand, and that the dungeon's own publication does not
// reach them. Counts come from the editor's read, which includes drafts and archived areas.
export function DungeonAreasReview({ view }: { view: DungeonAuthoringView | null }) {
    if (view === null) return null
    return (
        <p className="authoring-note">
            {view.areas.length === 0 ? "No areas yet." : areaTally(view.areas)} Publishing the dungeon does not
            publish its areas; each area is published on its own page once the dungeon is published.
        </p>
    )
}
