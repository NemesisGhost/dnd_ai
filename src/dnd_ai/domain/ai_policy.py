"""The policy engine docs/architecture/DATABASE_MODEL.md §18 describes: "a
policy engine determines whether a proposal may be applied automatically,
requires GM approval, or is rejected by validation."

Framework-free and pure (no database access) — the same posture
`dnd_ai.domain.access` keeps for its own authorization decisions. A
proposal's risk tier is a function of facts the caller has already
resolved (here: the knowledge item's own `sensitivity`), never re-derived
from raw request text.

This phase implements exactly one proposal kind (`reveal_knowledge`,
`dnd_ai.commands.ai_npc`/`.ai_proposals`) — the policy below is
correspondingly narrow; a future proposal kind adds its own classifier
function here rather than overloading this one.
"""

# docs/PLAN.md §18's own low-risk/high-impact framing, applied to knowledge
# sensitivity: revealing an already-authored public or merely-restricted
# fact is the "marking an already-authored hidden feature as discovered"
# case — low risk. A secret or dangerous fact is exactly the kind of
# high-impact disclosure PLAN.md §18 requires explicit approval for.
_AUTO_APPROVE_SENSITIVITIES = frozenset({"public", "restricted"})

RISK_TIER_AUTO_APPROVE = "auto_approve"
RISK_TIER_REQUIRES_APPROVAL = "requires_approval"


def classify_reveal_knowledge_risk(*, sensitivity: str) -> str:
    """Risk tier for a `reveal_knowledge` proposal, from the target
    knowledge item's own `knowledge.knowledge_items.sensitivity`. Returns
    one of `RISK_TIER_AUTO_APPROVE`/`RISK_TIER_REQUIRES_APPROVAL` — the two
    values `ai.proposed_changes.risk_tier`'s CHECK constraint allows."""
    if sensitivity in _AUTO_APPROVE_SENSITIVITIES:
        return RISK_TIER_AUTO_APPROVE
    return RISK_TIER_REQUIRES_APPROVAL
