import type { KnowledgeDetail } from "./knowledge"
import type { QuestDetail } from "./quest"

// The two resource kinds a GM may preview as a selected member — exactly
// the two genuine spoiler surfaces in the 13D read set (visibility_policy-
// driven, not capability-listing-driven): quest detail (hidden stages) and
// knowledge-item detail (per-knower belief versus ground truth). Never a
// third kind — see dnd_ai.api.preview's own module docstring.
export type AudiencePreviewResourceType = "quest" | "knowledge_item"

export type AudiencePreviewResult =
    | { resourceType: "quest"; quest: QuestDetail }
    | { resourceType: "knowledge_item"; knowledgeItem: KnowledgeDetail }
