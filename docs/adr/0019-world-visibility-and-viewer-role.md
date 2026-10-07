# ADR 0019: World visibility — campaign-derived reads, the `world_viewer` role, and ownership remediation

- **Status**: Accepted
- **Date**: 2026-10-06
- **Amended by**: [ADR 0020](0020-scoped-system-world-and-campaign-roles.md): the "may create worlds" policy of decisions 6 and 7 is now the system `gm` role (ADR 0018, which they cite, is superseded), a user may hold several world roles at once (the operator commands treat a user's roles as one set), and shared world canon now also needs a world capability. `world_viewer` and every other decision here are unchanged.
- **Builds on**: [ADR 0014](0014-world-authoring-authority.md) (per-world membership authority) and [ADR 0018](0018-world-creation-eligibility.md) (world creation limited to platform administrators and effective GMs). Neither is changed; this ADR adds a read-only world role, defines how a campaign member sees that campaign's world, and gives a remediation path for ownership granted before ADR 0018.

## Context

After ADR 0018 a local account showed three inconsistencies at once. The account (a player) owned a world it had created before ADR 0018, held the `player` role in one campaign, and held an active campaign membership with **no** role in a second campaign on the same world, which was also its last-visited campaign.

1. The session bootstrap listed every active membership in an active campaign, whether or not the membership carried `campaign.view`. The roleless campaign was listed, resumed as the startup campaign, and accepted as a stored preference, but every campaign route answered 403, so Campaign World showed "World unavailable".
2. `/worlds` listed only worlds with a `security.world_memberships` row. The world the player reached through their campaign was absent from All Worlds and from the hierarchy panel on `/worlds`, but the hierarchy panel added it on campaign routes, so the same account saw different world lists on different pages.
3. There was no way to give someone read-only access to a world outside a campaign, and no supported way to undo authoring access granted before ADR 0018 without deleting the world.

The world and timeline read models also computed `available_actions` from lifecycle state alone. That was harmless while `world_owner` was the only role, but any read-only role would have been offered edit, archive, timeline, and campaign-creation actions.

## Decision

1. **A campaign is offered only while the caller holds `campaign.view` in it.** The bootstrap (`dnd_ai.queries.bootstrap`), its preference-authorization helper, and therefore both preference writes require the resolved access context to carry `campaign.view`. A membership with no role, or with every role revoked, expired, inactive, or lacking `campaign.view`, is not listed, not chosen as the startup campaign, and dropped from stored preferences without disclosure. This is the same capability every campaign read route already required.
2. **`campaign.view` permits campaign-scoped World Explorer reads and nothing more.** It never becomes world authority: no world membership is created for campaign members, `/worlds/{id}` and every world/timeline route stay non-disclosing 404 for them, and it grants no `world.manage`, `timeline.manage`, `campaign.create`, or `world.create`.
3. **The portal presents one world list everywhere.** All Worlds and the hierarchy panel's World level both use `buildWorldChoices` (`portal/src/utils/worldAccess.ts`), which merges `GET /worlds` (explicit world authority) with the worlds of the bootstrap's campaigns:
   - one entry per `world_id`;
   - explicit world authority wins: the entry keeps its own capabilities and opens `/worlds/{worldId}`;
   - a world reachable only through campaigns opens `/app/{campaignId}/world` — the current route's campaign when it is on that world, otherwise the first such campaign in bootstrap order (name, then ID) — and is always marked read-only;
   - entries sort by case-insensitive name, then `world_id`; the list does not depend on the current route.
   Campaign-derived entries appear under the Active filter only: bootstrap campaigns are active, and an active campaign prevents its world from being archived.
4. **A new world role, `world_viewer`, carries `world.view` only** (revision `136_world_viewer_role`; mapping in `dnd_ai.domain.world_authority.WORLD_ROLE_CAPABILITIES`). It lists and reads the world, its timelines, and its calendars.
5. **Read models offer only actions the caller may take.** `WORLD_ACTION_CAPABILITIES` and `TIMELINE_ACTION_CAPABILITIES` map every reportable action to the capability its route and command enforce (`world.manage`, `timeline.manage`, or `campaign.create`). `get_world_detail` and `get_timeline_detail` drop an action the caller lacks the capability for from both `available_actions` and `blocked_actions`, so a viewer sees no action, blocked or not. The portal already renders from `available_actions` and `capabilities`, so a viewer gets read-only pages and every authoring route renders not-found or "cannot be …" without mounting a form. Routes answer a viewer's mutation with 403 and commands refuse it under their own locks.
6. **World memberships stay trusted-infrastructure administration in the current product scope.** There is no HTTP route or portal control for them. `dnd_ai.commands.world_memberships` (`set_world_role`, `end_world_membership`, `transfer_world_ownership`) and `scripts/manage_world_membership.py` (preview by default, `--apply`, one audit row per membership row opened or closed) are the supported path. They lock the world row first, close and open rows rather than editing them, refuse to leave a world without an active owner, and grant `world_owner` only to an account that satisfies the ADR 0018 creation policy.
7. **Legacy unauthorized ownership is remediated explicitly, never silently.** No migration or startup step revokes ownership or deletes a world. An operator lists open `world_owner` memberships whose holders no longer satisfy ADR 0018 (`--list-ineligible-owners`) and transfers ownership to an eligible account, optionally leaving the former owner `world_viewer` (`--retain-viewer`). The former owner keeps whatever their campaign roles grant, including `campaign.view` reads of each campaign's World Explorer, and gains no authoring access.
8. **The development fixture describes the database it builds.** `scripts/setup_phase13c_dev_data.py` documents which campaigns each Phase 13E account belongs to; a re-run now ends a stray membership that contradicts that (for example one added from the Access page during manual testing) through `end_campaign_membership`, with audit, instead of leaving an inaccessible membership in place.

## Alternatives considered

- **Create `world_viewer` memberships for every campaign member automatically.** Rejected: it duplicates authority that the campaign already expresses, has to be kept in sync with every role and membership change, and would give a former player continued world access after leaving a campaign.
- **Return campaign-visible worlds from `GET /worlds`.** Deferred: the bootstrap already carries each authorized campaign's world identity, and `/worlds` would need a second, campaign-shaped result type and a keyset over a union. One portal helper keeps the rule in one place for both lists.
- **Show a campaign-derived world on `/worlds/{id}` read-only.** Rejected: world routes are governed by world roles. A campaign member's view of world content is the campaign's audience-filtered World Explorer, not the world's authoring overview.
- **Revoke pre-ADR-0018 ownership in a migration.** Rejected: it would silently remove the only owner of real worlds, and the owner-retention trigger requires a successor anyway.
- **Edit `security.world_roles.yaml`.** Rejected: revision 110 consumed it, so it is frozen (DATABASE_CONVENTIONS §25.4); revision 136 inserts the row explicitly.

## Consequences

- A membership without `campaign.view` no longer appears anywhere a user chooses a campaign. Tests that built bare memberships to exercise the bootstrap now give them a role.
- World and timeline detail responses can now differ by caller; owners see exactly what they saw before.
- `world_viewer` access can only be granted by an operator until world-membership administration enters product scope; at that point the commands above are the write path an API would call.
- An ineligible historical owner keeps ownership until an operator acts; `--list-ineligible-owners` makes that state visible.

## References

- [ADR 0014](0014-world-authoring-authority.md), [ADR 0018](0018-world-creation-eligibility.md)
- [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) — World authority
- [DATABASE_MODEL.md §19.2a](../architecture/DATABASE_MODEL.md) — `security.world_roles`, `security.world_memberships`
- [UI_DESIGN.md §4.1, §4.4, §4.7](../UI_DESIGN.md)
- `src/dnd_ai/queries/bootstrap.py`, `src/dnd_ai/domain/world_authority.py`, `src/dnd_ai/queries/worlds.py`, `src/dnd_ai/queries/timeline_detail.py`, `src/dnd_ai/commands/world_memberships.py`, `scripts/manage_world_membership.py`, `portal/src/utils/worldAccess.ts`
