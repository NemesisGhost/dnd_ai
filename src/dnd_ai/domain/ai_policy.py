"""The policy engine docs/architecture/DATABASE_MODEL.md §18 describes: "a
policy engine determines whether a proposal may be applied automatically,
requires GM approval, or is rejected by validation."

Framework-free and pure (no database access) — the same posture
`dnd_ai.domain.access` keeps for its own authorization decisions. A
proposal's risk tier is a function of facts the caller has already
resolved (here: the knowledge item's own `sensitivity`), never re-derived
from raw request text.

This phase implements two proposal kinds: `reveal_knowledge` (`dnd_ai.
commands.ai_npc`/`.ai_proposals`) and `advance_quest_objective` (same
modules, dispatching to `dnd_ai.commands.quests._advance_objective_impl`).
Each kind gets its own classifier function here rather than overloading one
shared function — the policy question ("what risk tier does this proposal
get?") genuinely differs per kind, even though both currently resolve via a
simple lookup.
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


def classify_advance_quest_objective_risk(*, new_status_code: str) -> str:  # noqa: ARG001
    """Risk tier for an `advance_quest_objective` proposal — always
    `RISK_TIER_REQUIRES_APPROVAL`, for both `'completed'` and `'failed'`.

    `new_status_code` is accepted (and validated by the caller to be one of
    those two values before this is ever called) but deliberately never
    changes the answer: completing or failing a quest objective is a
    consequential, narratively irreversible canonical mutation — exactly
    docs/architecture/DATABASE_MODEL.md §18's "high-impact approval-required"
    category ("permanent quest failure" is named there explicitly, and a
    completion is symmetrically consequential), never the "marking an
    already-authored hidden feature as discovered" low-risk case
    `classify_reveal_knowledge_risk` sometimes auto-approves. Unlike that
    function, there is no safe narrower auto-approve subset here: every
    quest objective this phase can reach is already GM-authored, campaign-
    relevant progress, not a low-stakes cosmetic detail — so this always
    returns the stricter tier rather than inventing a discriminating
    condition just to exercise the auto-approve branch."""
    return RISK_TIER_REQUIRES_APPROVAL
