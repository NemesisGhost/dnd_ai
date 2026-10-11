import { DetailPanel } from "../components/DetailPanel"
import { FactGrid } from "../components/FactGrid"
import { HitPointsMeter } from "../components/HitPointsMeter"
import type { CharacterDetail } from "../types/character"

interface CharacterDetailPageProps {
    character: CharacterDetail
}

// The restricted World character read model: only the fields the audience-safe response carries.
// It shares the World readers' panel and fact vocabulary, but is not the character sheet.
export function CharacterDetailPage({
    character,
}: CharacterDetailPageProps) {
    const conditions = character.conditions
    const resources = character.resources

    const hasFullDetails =
        conditions !== null &&
        resources !== null

    return (
        <section aria-labelledby="character-heading">
            <p className="world-detail__eyebrow">Character</p>
            <h1 id="character-heading">{character.name}</h1>

            <div className="world-detail__panel-grid">
                <DetailPanel title="Overview" headingId="character-overview-heading">
                    <FactGrid
                        items={[
                            { key: "species", label: "Species", value: character.species_code },
                            { key: "size", label: "Size", value: character.size_category },
                        ]}
                    />
                </DetailPanel>
                {hasFullDetails ? (
                    <>
                        <DetailPanel title="Current state" headingId="character-current-state-heading">
                            <FactGrid
                                items={[
                                    {
                                        key: "hit-points",
                                        label: "Hit points",
                                        value:
                                            character.current_hit_points !== null &&
                                            character.maximum_hit_points !== null ? (
                                                <HitPointsMeter
                                                    currentHitPoints={character.current_hit_points}
                                                    maximumHitPoints={character.maximum_hit_points}
                                                />
                                            ) : (
                                                "Not recorded"
                                            ),
                                    },
                                    {
                                        key: "temporary-hit-points",
                                        label: "Temporary hit points",
                                        value: character.temporary_hit_points ?? "Not recorded",
                                    },
                                    {
                                        key: "exhaustion",
                                        label: "Exhaustion level",
                                        value: character.exhaustion_level ?? "Not recorded",
                                    },
                                    {
                                        key: "death-save-successes",
                                        label: "Death save successes",
                                        value: character.death_save_successes ?? "Not recorded",
                                    },
                                    {
                                        key: "death-save-failures",
                                        label: "Death save failures",
                                        value: character.death_save_failures ?? "Not recorded",
                                    },
                                ]}
                            />
                        </DetailPanel>
                        <DetailPanel
                            title="Conditions"
                            headingId="character-conditions-heading"
                            isEmpty={conditions.length === 0}
                            emptyState={<p className="detail-panel__empty">No conditions are currently recorded.</p>}
                        >
                            <ul className="world-detail__list">
                                {conditions.map((condition) => (
                                    <li key={condition.condition_code}>
                                        <strong>{condition.condition_code}</strong>
                                        {condition.source_description !== null && (
                                            <>{" - "}{condition.source_description}</>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        </DetailPanel>
                        <DetailPanel
                            title="Resources"
                            headingId="character-details-resources-heading"
                            isEmpty={resources.length === 0}
                            emptyState={<p className="detail-panel__empty">No resources are currently recorded.</p>}
                        >
                            <ul className="world-detail__list">
                                {resources.map((resource) => (
                                    <li key={resource.resource_code}>
                                        <strong>{resource.resource_code}</strong> {": "} {resource.current_amount} /{" "} {resource.maximum_amount}
                                    </li>
                                ))}
                            </ul>
                        </DetailPanel>
                    </>
                ) : null}
            </div>
            {hasFullDetails ? null : <p>Additional character details are not available.</p>}
        </section>
    )
}
