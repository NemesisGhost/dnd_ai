# P03-A A1 design: campaign-owner authority (D3)

- **Status:** D3 **approved by the owner on 2026-11-06** (policy in §5) and **implemented** as the first A1 change (the ownership gate only; the reveal-delegation migration and API are the next A1 change). Awaiting independent review.
- **Baseline:** `phase15/completion` at `fca3ac7df7e7a88822cc90acbed052ca07a1026c` (A0 committed).
- **Audience:** the owner deciding D3; the A1 implementer and reviewers.
- **Parent plan:** [PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md), decision D3 and slice A1.
- **Governing documents:** [ADR 0020](adr/0020-scoped-system-world-and-campaign-roles.md) (decisions 7 and 9), [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) §2.7–§2.8 and §6, the owner-approved `character.reveal` policy (2026-11-06, recorded in [PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md](PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md)), [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](SCOPED_ROLE_IMPLEMENTATION_PLAN.md) §4.2, §4.5 and §7, [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) §3a.

## Entry verdict

D3 is answered (§5). Nothing else blocks A1. D1, D2 and D5 gate only A2–A3. The change needs no schema migration.

## 1. The problem

In A1, direct reveal authority comes from holding a live built-in `campaign_owner` assignment. Anyone who can give themselves that role therefore gets reveal.

Almost every route that hands out `campaign_owner` checks only `access.manage`. That check reads role capabilities only ([access.py:1029-1046](../src/dnd_ai/domain/access.py#L1029-L1046)): an untargeted `has_capability` call never consults resource grants. Resource grants and relationships can never supply `access.manage` anyway, because the grant catalog ([access.py:226](../src/dnd_ai/domain/access.py#L226)) and the relationship matrix both leave it out.

So a non-owner can hold `access.manage` only through a custom role capability: a campaign-scoped role, or an extra `security.role_capabilities` row on a built-in role. No app path writes either today; migration 085's docstring confirms there is no endpoint for creating roles or capabilities. But:

- the schema allows them;
- migration 086 says an owner may add `access.manage` to another role "one row at a time";
- dozens of database test fixtures build exactly that kind of custom admin role with `make_role_capability`.

## 2. Every path that creates or restores a campaign owner

| Path | Check that actually applies | Can a custom `access.manage` holder get reveal today? | If custom grants were enabled |
|---|---|---|---|
| `create_campaign` ([campaigns.py:613](../src/dnd_ai/commands/campaigns.py#L613)) | System `campaign.host` + world `campaign.create`; the owner is the creator, in a brand-new campaign | No | Safe: ownership of a new campaign gives nothing in any other campaign |
| `assign_membership_role` ([api :260](../src/dnd_ai/api/memberships.py#L260) → [cmd :337](../src/dnd_ai/commands/memberships.py#L337)) | `access.manage`; the role must be built-in or belong to this campaign; the target must be active. Assigning to yourself is allowed | No | **Bypass:** they can assign `campaign_owner` to themselves |
| `change_membership_role` ([api :422](../src/dnd_ai/api/memberships.py#L422) → [cmd :591](../src/dnd_ai/commands/memberships.py#L591)) | Same checks | No | **Bypass:** they can change their own custom role row into `campaign_owner` |
| `add_campaign_member` ([api :155](../src/dnd_ai/api/memberships.py#L155) → [cmd :779](../src/dnd_ai/commands/memberships.py#L779)) | `access.manage`; campaign active; account active with a local login | No | **Bypass by proxy:** they can add a second account they control as owner |
| `transfer_campaign_ownership` ([api :629](../src/dnd_ai/api/memberships.py#L629) → [cmd :1206](../src/dnd_ai/commands/memberships.py#L1206)) | `access.manage` only. The target can be the caller. "Relinquish" does nothing for a non-owner | No | **Bypass:** they can transfer ownership to themselves |
| `recover_campaign_access_manager` ([recovery.py:129](../src/dnd_ai/commands/recovery.py#L129)) | Operator script, active admin, a required reason, and no active non-expiring `access.manage` holder in the campaign ([recovery.py:148](../src/dnd_ai/commands/recovery.py#L148)) | No (admin only) | Not a bypass, but a recovery gap (§3, "Left out on purpose") |
| Invitation acceptance ([campaign_invitations.py:247](../src/dnd_ai/commands/campaign_invitations.py#L247)) | Invitation from an `access.manage` holder; acceptance reopens the same membership and gives no role | No | Only by data: an ended membership that still has a live owner role row would get it back. `end_campaign_membership` revokes every role row, so the app never creates one. The preflight in §6 checks |
| Role expiry lapsing, role `is_active`, membership suspension | No app path writes these | — | Only ever removes authority |

**Bottom line:** there is no bypass through the app today. Four routes become bypasses the moment any non-owner role carries `access.manage`, and today that only takes an operator writing to the database directly.

## 3. Recommended change: the smallest one

1. **One shared owner check.** Put the "live built-in owner" test in the domain module that A1's reveal-authority resolver uses, so the two can't drift apart. "Live" means:
   - the role row is the built-in template (`campaign_id IS NULL`, `code = 'campaign_owner'`), matched by `role_id`, never by code alone (`security.roles.code` is unique only among templates);
   - the assignment is not revoked and not expired, and the role is active;
   - the membership is open and active, and the account is active.

   Add a command helper, `_require_builtin_campaign_owner(connection, campaign_id, actor_membership_id)`, that locks the caller's owner assignment row `FOR SHARE` and otherwise refuses with **403 `campaign_owner_required`**.

2. **Call it only when the role being granted is the built-in `campaign_owner`:**
   - in `assign_membership_role`, after its existing membership, user and role locks;
   - in `change_membership_role` when `new_role_id` is the owner role;
   - in `add_campaign_member` when the initial role is the owner role;
   - at the top of `transfer_campaign_ownership`, so a non-owner can't get a 200 `assigned: false` answer back as a probe.

   Every role other than owner stays exactly as it is today. The commands already receive the caller's membership as `granted_by_membership_id` or `actor_membership_id`, so no signatures change.

   **Lock order (as implemented; this replaces the proposal's "after the existing locks").** The caller's owner assignment is the **first** lock every gated command takes. Revoke, change, end-membership and relinquish all update that row, so whichever commits first wins: a revocation that commits first gets the assignment refused, and nothing is checked against a cached `AccessContext`. Taking it last, as first proposed, was traced against the real paths and rejected: `change_membership_role` (holding the target's membership and the owner template, then wanting the owner row) and a relinquishing `transfer_campaign_ownership` (holding the owner row, then wanting the target's membership) wait on each other when the same owner issues both, and `add_campaign_member` (holding the campaign row, then wanting the owner row) cycles with a revocation's commit-time retention trigger, which takes the campaign row. Owner-first removes both cycles.

   Two further rules came out of the same trace and are pinned by `tests/database/test_campaign_owner_gate.py`:

   - A relinquishing transfer takes the owner row `FOR UPDATE` (not `FOR SHARE`) up front. A shared lock followed by the later revoke is a lock upgrade, which deadlocks two identical concurrent requests.
   - A relinquishing transfer then locks the campaign row before reading current owners. Without it, two owners relinquishing to each other at once each saw the other as the remaining owner and both committed, leaving the campaign with no built-in owner (the commit-time retention rule needs only some `access.manage` holder, and a custom manager satisfied it). The order is owner assignment, then campaign, the same order the retention trigger uses.

   Known residual: an owner assigning the owner role to their own membership while that membership is being ended can still be resolved by PostgreSQL's deadlock detector (one request fails and can be retried). Assigning the owner role to a membership that already holds it is a unique-index conflict anyway.

3. **Server-side role list.** `list_assignable_campaign_roles` ([access_overview.py:436](../src/dnd_ai/queries/access_overview.py#L436)) takes the caller's membership and leaves out the built-in owner role unless the caller is a live owner. The portal is never offered an action that would be refused.

4. **No database trigger.** Campaign creation, recovery and test factories all insert owner rows with `granted_by_membership_id = NULL`, so a trigger couldn't tell legitimate inserts apart. Authorization stays at the application layer, where every other campaign-role check already lives.

**Left out on purpose.** Recovery, and every path that revokes or ends an owner, stays unchanged. A custom manager revoking an owner doesn't give anyone reveal. Two issues only matter once custom `access.manage` gets an app path, so they are recorded as conditions on that future work:

- the recovery precondition and the stranded-campaign reports ([stranded.py:45](../src/dnd_ai/queries/stranded.py#L45)) look for any `access.manage` holder. With a custom manager present, an admin couldn't restore an owner, so the campaign would permanently lose reveal authority;
- the database retention rule (`security.campaign_has_access_manager`, migration 080) only guarantees that someone holds non-expiring `access.manage`. It does not guarantee a built-in owner exists.

## 4. What changes against ADR 0020

ADR 0020 doesn't mention campaign transfer itself. The behavior comes from documents it points to:

- [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](SCOPED_ROLE_IMPLEMENTATION_PLAN.md) §4.2: "Invite to a campaign; assign campaign roles: campaign `access.manage` (unchanged)" and "Transfer campaign ownership: campaign `access.manage`";
- the same plan's §7 entry: `POST /campaigns/{id}/ownership-transfer` (`access.manage`);
- [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) §3a and the `assignable_roles` read contract, which say every role an `access.manage` holder may assign is equally assignable because the role model is flat.

All three change for exactly one role. Nobody using an app-created campaign would notice, because today every `access.manage` holder is a built-in owner. ADR 0020 decision 7 (authorship is provenance) and decision 9 (explicit, audited recovery) are unchanged. A1 updates the three documents in the same change and adds an amendment note to ADR 0020.

## 5. Decision D3 (approved 2026-11-06)

The owner's decision, in substance:

> Assigning the built-in `campaign_owner` role, changing a member to that role, adding a member with that role, or transferring ownership requires both `access.manage` and a live built-in owner assignment in the same campaign. Existing rules for other roles, campaign creation and administrative recovery are preserved. Existing reveal delegations survive transfer. Relinquishing ownership ends owner-derived reveal authority. A separate GM delegation still applies while its original GM assignment remains live. Only a current owner may grant or revoke delegations.

The reveal-delegation rules in the last four sentences are implemented by the next A1 change (migration, resolver, commands and API). This change implements the first sentence and the shared live-owner check the resolver will reuse (`find_live_builtin_owner_assignment`).

## 6. Regression tests (database and API)

**The bypass is closed.** Use the existing fixture style: a campaign-scoped role given `access.manage` with `make_role_capability`.

- A custom manager who assigns, changes or adds `campaign_owner`, or transfers ownership to self, to someone else or to an existing owner, gets 403 `campaign_owner_required`. Each case leaves no new row and no audit entry, nothing is half-written, and the reveal resolver still returns `none`.
- The same refusals happen when the commands are called directly, so a future route can't skip the check.
- A custom manager can still assign `gm` and `player`, and holding `gm` still gives no reveal.
- The role list hides `campaign_owner` from a custom manager and shows it to an owner.
- A campaign-scoped custom role with the code `campaign_owner` gives no reveal and isn't affected by the gate.

**Legitimate paths still work.**

- [test_stranding_and_recovery.py:206](../tests/database/test_stranding_and_recovery.py#L206) and `:267` pass unchanged.
- An owner can make a co-owner, and can add a new member as owner.
- A campaign's creator gets `owner` from the reveal resolver.
- Recovery works as before, and the recovered owner gets `owner` from the reveal resolver.
- An owner whose own owner assignment has expired, or whose membership is no longer active, is refused.
- Concurrency:
  - when an owner's role is revoked at the same moment they assign the owner role, the revocation commits first and the assignment is refused, or the assignment commits first and the revocation then waits for it;
  - two owners transferring to each other at once don't deadlock.

**Ownership transfer and existing delegations.**

- Owner O delegates reveal to GM G, then transfers to N and relinquishes:
  - G's delegation row is unchanged, `granted_by` still names O, and G's resolver returns `delegation`;
  - O's resolver returns `none` and N's returns `owner`;
  - O can no longer grant or revoke (403), and N can revoke G's delegation.
- A transfer without relinquishing leaves both as owners, and either can revoke.
- A transfer to G itself gives G `owner`, and G's delegation row stays. After G later relinquishes, the delegation still applies while G's `gm` row is live.
- A repeated transfer changes nothing: no audit entry and no delegation change.
- A transfer in campaign A leaves campaign B's delegations untouched.

**Preflight** (a read-only query in A1's upgrade check, not a migration):

- count `access.manage` rows on any role other than the built-in owner;
- count live owner role rows on ended or inactive memberships.

If either count is not zero, the deployment would see the gate change behavior, or could have an owner revived by an invitation.

## 7. Follow-ups recorded outside D3

Both are recorded in the [defect register](PHASE14_15_DEFECT_REGISTER.md) §9 as proposed gradings, are not fixed here, and are checked by `scripts/preflight_campaign_owner_gate.py`.

- **F1 (DEF-011), expired-target transfer.** `transfer_campaign_ownership` looks for the target's existing owner row using only `revoked_at IS NULL` (the `already` query in [memberships.py](../src/dnd_ai/commands/memberships.py)). A target whose owner assignment expired but was never revoked reads as already owning: the transfer reports `assigned: false` and still lets the caller relinquish. The retention rule then refuses (400) or leaves the campaign with whoever else manages it. Assigning a fresh row would instead hit `ux_membership_roles_active`, because the expired row is still unrevoked. Reachable today: `POST …/memberships/{id}/roles` accepts `expires_at`.
- **F2 (DEF-012), recovery gap.** `recover_campaign_access_manager` and the stranded-campaign report look for any non-expiring `access.manage` holder. When a custom role is the only `access.manage` holder and no live built-in owner exists, an administrator cannot restore an owner and the campaign permanently loses owner-derived reveal authority. Not reachable through an application path today (no endpoint writes custom role capabilities).

## 8. Implementation record (2026-11-06)

- Shared check: `dnd_ai.domain.access.find_live_builtin_owner_assignment` (optional row lock) and `is_builtin_campaign_owner_role`. The reveal resolver reuses the first.
- Gate: `_require_builtin_campaign_owner` / `_require_owner_if_granting_owner_role` in `commands/memberships.py`, in `assign_membership_role`, `change_membership_role`, `add_campaign_member` and `transfer_campaign_ownership`. Refusal is `CampaignOwnerRequiredError`, 403 `campaign_owner_required`.
- Role list: `list_assignable_campaign_roles` takes the caller's membership and omits the built-in owner role unless the caller is a live owner.
- Preflight (local development database, read-only, 2026-11-06): all four counts zero (non-owner `access.manage` roles 0; live owner rows on ended or inactive memberships 0; expired unrevoked owner rows 0; active campaigns without a live owner 0).
- Not changed: schema, recovery, campaign creation, invitation acceptance, every non-owner role path.
