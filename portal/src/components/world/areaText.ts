import type { AreaSummary } from "../../types/dungeonAuthoring"

export const plural = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`

// What an area holds, in words. Counts come from the editor's definition read, so they include
// concealed children; they are never shown to a reader.
export function contentsText(area: AreaSummary): string {
    const parts = [
        area.feature_count > 0 ? plural(area.feature_count, "feature", "features") : null,
        area.hazard_count > 0 ? plural(area.hazard_count, "hazard", "hazards") : null,
        area.interactable_count > 0 ? plural(area.interactable_count, "interactable", "interactables") : null,
    ].filter((part) => part !== null)
    return parts.length === 0 ? "No contents" : parts.join(" · ")
}

// Each area's own status, counted. An archived area counts as archived whatever its canon status.
export function areaTally(areas: AreaSummary[]): string {
    const count = (match: (area: AreaSummary) => boolean): number => areas.filter(match).length
    const live = (area: AreaSummary): boolean => area.lifecycle_status !== "archived"
    const parts = [
        [count((a) => live(a) && a.canon_status === "canon"), "published"],
        [count((a) => live(a) && a.canon_status === "draft"), "draft"],
        [count((a) => live(a) && (a.canon_status === "proposed" || a.canon_status === "approved")), "in review"],
        [count((a) => live(a) && a.canon_status === "rejected"), "rejected"],
        [count((a) => live(a) && a.canon_status === "superseded"), "replaced"],
        [count((a) => !live(a)), "archived"],
    ].filter(([n]) => n !== 0)
    return `${plural(areas.length, "area", "areas")}${parts.length === 0 ? "" : `: ${parts.map(([n, word]) => `${n} ${word}`).join(", ")}`}.`
}
