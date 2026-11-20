# Worlds, people and play

A world holds shared definitions. A timeline orders events and their effects in fictional time. A campaign selects its world, timeline and ruleset version and supplies the people and authority for play. A session records an episode of that campaign. Scheduling a real-world meeting, recording a named world time and advancing the campaign clock are three separate operations. [Domain vocabulary](../DOMAIN_MODEL.md) · [Fictional time intervals](../adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md)

## Who can act

A local account identifies a person. System roles govern platform administration and eligibility to create worlds or host campaigns. World Owner, Editor, Reviewer, Reader and legacy Viewer assignments have world scope. Sharing also has a separate grant to host a campaign. A campaign membership, its current roles, the selected character relationship, direct grants and group grants can all matter to a request. Signing in or administering accounts alone conveys no routine world authorship. [Scoped-role decision](../adr/0020-scoped-system-world-and-campaign-roles.md) · [Access contracts](../api/ACCESS_CONTROL.md)

A character has a shared identity and narrative across campaigns. Controlling the character during play, contributing to its player profile, editing a shared canonical definition and deciding what an audience learns are separate permissions. The accepted design places mechanical state under campaign authority and permits bounded player contributions. Migration to that model and player-facing writing are still delivery work. The existing player-profile storage, GM read and eligible-field copy into a public **draft** do not provide a production player editor. GM portrayal stays private. [Shared actor decision](../adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) · [Implementation and review gates](../delivery/work-register.md#maintained-work-register)

## From authoring to discovery

An authorized author creates a typed draft. Review and publication govern which definition is canonical. Revision history preserves the authored record. A GM can choose eligible fields for a campaign's public character profile and release that profile. A release is an editorial act. Revelation selects an audience, and access checks still apply to the resulting read. Keeping a private source restricted matters even when copying a field. [Entity lifecycle](../ENTITY_LIFECYCLE.md) · [Public-profile contract](../api/ACCESS_CONTROL.md#3v-character-public-profile-p03-a-a2a)

Knowledge records what a knower or party has learned or believes. It can differ from the truth of the world and from another party's knowledge. A hidden door can exist in canonical geography before anyone discovers it. Publishing a location does not tell every party how to enter it. [Knowledge decision](../adr/0007-separate-knowledge-from-truth.md)

## What a branch inherits

A branch has a parent and a branch point. Effective event history follows ancestors only through that point. Later changes on the parent must stay on the parent. Event history, campaign clock resolution and active character builds have ancestry-aware reads. Dungeon typed state and quest/objective progress currently look up rows on the selected timeline. A child may therefore show a default or omit a tracked quest even when the parent changed before the fork. Party membership follows its own timeline and interval rules. [Branch contract and current limitation](../ENTITY_LIFECYCLE.md#9-branching-timelines)
