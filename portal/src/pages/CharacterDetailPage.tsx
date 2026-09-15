import { HitPointsMeter } from "../components/HitPointsMeter"
import type { CharacterDetail } from "../types/character"

interface CharacterDetailPageProps {
    character: CharacterDetail
}

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
            <h1 id="character-heading">{character.name}</h1>
            <section aria-labelledby="character-overview-heading">
                <h2 id="character-overview-heading">Overview</h2>
                <dl>
                    <div>
                        <dt>Species</dt>
                        <dd>{character.species_code}</dd>
                    </div>

                    <div>
                        <dt>Size</dt>
                        <dd>{character.size_category}</dd>
                    </div>
                </dl>
            </section>
            {hasFullDetails ? (

                <>
                    <section aria-labelledby="character-current-state-heading">
                        <h2 id="character-current-state-heading">Current state</h2>
                        <dl>
                            <div>
                                <dt>Hit points</dt>
                                <dd>
                                    {character.current_hit_points !== null && character.maximum_hit_points !== null ? (
                                        <HitPointsMeter
                                            currentHitPoints={character.current_hit_points}
                                            maximumHitPoints={character.maximum_hit_points}
                                        />
                                    ) : (
                                        "Not recorded"
                                    )}
                                </dd>
                            </div>
                            <div>
                                <dt>Temporary hit points</dt>
                                <dd>{character.temporary_hit_points ?? "Not recorded"}</dd>
                            </div>
                            <div>
                                <dt>Exhaustion level</dt>
                                <dd>{character.exhaustion_level ?? "Not recorded"}</dd>
                            </div>
                            <div>
                                <dt>Death save successes</dt>
                                <dd>{character.death_save_successes ?? "Not recorded"}</dd>
                            </div>
                            <div>
                                <dt>Death save failures</dt>
                                <dd>{character.death_save_failures ?? "Not recorded"}</dd>
                            </div>
                        </dl>
                    </section>
                    <section aria-labelledby="character-conditions-heading">
                        <h2 id="character-conditions-heading">Conditions</h2>
                        {conditions.length > 0 ? (
                            <ul>
                                {conditions.map((condition) => (
                                    <li key={condition.condition_code}>
                                        <strong>{condition.condition_code}</strong>
                                        {condition.source_description !== null && (
                                            <>{" - "}{condition.source_description}</>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p>No conditions are currently recorded.</p>
                        )}
                    </section>
                    <section aria-labelledby="character-details-resources-heading">
                        <h2 id="character-details-resources-heading">Resources</h2>
                        {resources.length > 0 ? (
                            <ul>
                                {resources.map((resource) => (
                                    <li key={resource.resource_code}>
                                        <strong>{resource.resource_code}</strong> {": "} {resource.current_amount} /{" "} {resource.maximum_amount}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p>No resources are currently recorded.</p>
                        )}
                    </section>
                </>
            ) : (
                <p>Additional character details are not available.</p>
            )}
        </section>
    )
}