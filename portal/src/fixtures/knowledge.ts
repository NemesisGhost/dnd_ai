import type {
    KnowledgePage,
} from "../types/knowledge"

export const knowledgePageFixture = {
    items: [
        {
            knowledge_item_id:
                "knowledge-glass-ossuary",
            knowledge_type_code: "fact",
            statement:
                "The Glass Ossuary was built to preserve divine remains.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "understood",
            confidence: 85,
            willing_to_share: true,
            scope: "party",
            discovery_world_time_id:
                "world-time-ossuary-discovery",
            source_event_id:
                "event-ossuary-entry",
            source_interaction_id: null,
            subject_entity_id:
                "location-glass-ossuary",
        },
        {
            knowledge_item_id:
                "knowledge-drowned-shard",
            knowledge_type_code: "rumor",
            statement:
                "The Drowned Shard may contain the power of a forgotten god.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "heard",
            confidence: 40,
            willing_to_share: false,
            scope: "party",
            discovery_world_time_id: null,
            source_event_id: null,
            source_interaction_id: null,
            subject_entity_id: null,
        },
    ],
    next_cursor: "next-knowledge-page",
} satisfies KnowledgePage