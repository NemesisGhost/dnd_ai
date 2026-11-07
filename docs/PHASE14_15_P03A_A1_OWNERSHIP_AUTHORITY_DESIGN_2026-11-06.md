# P03-A A1 design: campaign-owner authority (D3)

- **Status:** D3 **approved by the owner on 2026-11-06** (policy in §5) and **implemented** as the first A1 change (the ownership gate only; the reveal-delegation migration and API are the next A1 change). A review found two deadlocks in the first implementation's lock order; the corrected order is in §3. The independent re-review of the corrected commit (`fc20e8d`) passed, with 107 focused tests passing (result as reported by the reviewer; the review text is not in the repository). One verification item stays open: an intermittent race-test timeout seen in earlier long runs (request alive, no lock waiter within 15 s) is **unresolved**. Its cause is not proven and the fix does not claim to address it. Full backend suite on the corrected commit's content: 6929 passed, 0 failed, no race-test timeout (one run, 2026-11-06; run with `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS` pinned to its documented default so the repository `.env` override does not fail the config default test). One clean run does not resolve the flake. CI is pending until push.
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

   **Lock order (verified; corrected 2026-11-06 after review).** One order for every command that touches these rows. A command takes only the locks it needs, always in this sequence:

   1. the member's role rows (for a gated command, the caller's own live owner assignment, `FOR SHARE`, or `FOR UPDATE` when it will rewrite that row);
   2. the membership row(s);
   3. the account row and the role template rows (`security.users`, `security.roles`);
   4. the campaign row, which the retention trigger takes at commit and a relinquishing transfer takes explicitly.

   The trigger (`tr_membership_roles_retain_access_manager`, `tr_campaign_memberships_retain_access_manager`, migration 080) fires only on UPDATE or DELETE, so it takes the campaign row at commit for revoke, change, end-membership and relinquish, and not for an INSERT-only assign. Every command that holds a membership row therefore reaches the campaign row after it.

   | Command | Locks, in order |
   |---|---|
   | `assign_membership_role` (owner role) | caller's owner assignment (S) → target membership → target account → role template; insert only, no campaign lock |
   | `change_membership_role` (to owner) | caller's owner assignment (S) → target role row + membership + current role → new role template → campaign at commit |
   | `add_campaign_member` (owner role) | caller's owner assignment (S) → campaign (FOR UPDATE) → account → role template |
   | `transfer_campaign_ownership` (relinquishing) | caller's owner assignment (U) → recipient's already-expired owner row (U) → recipient's membership → recipient's account (key share) → owner template → campaign (FOR UPDATE) → `assign_membership_role`'s own locks (already held; the recipient's account is raised to U when they are not yet an owner) → revoke of the caller's row → caller's account (key share, the audit row's foreign key) |
   | `transfer_campaign_ownership` (not relinquishing) | caller's owner assignment (S) → recipient's already-expired owner row (U) → `assign_membership_role` → caller's account (key share) |
   | `end_campaign_membership` | the member's active role rows (U, by id) → membership → character relationships, grants, groups → campaign at commit |
   | `revoke_membership_role` | the role row → campaign at commit |
   | `grant_character_reveal_delegation` | caller's owner assignment (S) → grantee's built-in `gm` assignment rows (U) → grantee's membership (**NO KEY UPDATE**) → grantee's delegation rows (U) → caller's membership and the campaign row (**KEY SHARE** only, the locks the insert's foreign keys take, taken here so any wait is behind the re-check); fresh-time re-check of the caller and the grantee's `gm` assignment; close stale rows, insert |
   | `revoke_character_reveal_delegation` | caller's owner assignment (S) → grantee's live delegation row (U) → caller's membership (KEY SHARE, for the `revoked_by` foreign key); fresh-time re-check of the caller; close. No campaign lock |
   | `revoke_membership_role` / `change_membership_role` (the closing hook) | already hold the role row; the delegation bound to it is the next lock, ahead of the campaign row at commit |
   | `end_campaign_membership` (the closing hook) | already holds the member's role rows and membership; the member's delegation is the next lock, after the relationship, grant and group rows and ahead of the campaign row at commit |

   Two reported races, both now ordinary outcomes and pinned by `tests/database/test_campaign_owner_lock_order.py`:

   - **Relinquishing transfer against ending the recipient's membership.** The first version of the zero-owner guard took the campaign row before the recipient's membership, while `end_campaign_membership` holds the membership and takes the campaign row at commit: each waited on the other. Now the transfer takes the membership first and the campaign last. Whichever runs first wins. A recipient ended first is refused under the locks by `assign_membership_role`'s eligibility check (409, the caller keeps ownership, no audit row). A transfer that runs first leaves the end to end a recipient who has become an owner.
   - **Owner assigning themselves the owner role against ending that owner's membership.** The assignment held the owner assignment and wanted the membership; the end held the membership and wanted the owner assignment. The end now locks the member's role rows before the membership row, so it queues behind the assignment. An assignment that wins the lock fails on the unique index (409); an end that wins makes the assignment fail its owner check (403).

   Other rules from the same trace:

   - A relinquishing transfer takes the caller's owner assignment `FOR UPDATE` up front. A shared lock followed by the later revoke is a lock upgrade, which deadlocks two identical concurrent requests.
   - The zero-owner guard is the campaign row, taken after the recipient's membership and the owner template. Two owners relinquishing to each other at once then serialize, and the second re-reads the first's committed result: both succeed and exactly one owner remains.
   - The recipient's account row is never locked `FOR UPDATE` early. The audit insert's foreign key to the caller's account needs a key-share lock, so an early `FOR UPDATE` on that account in the other half of a mutual transfer produced a deadlock only visible through the HTTP route. A relinquishing transfer takes it `FOR KEY SHARE` instead, right after the recipient's membership (see "Recipient account deactivation" below), which never conflicts with that key-share lock. `assign_membership_role` raises it to `FOR UPDATE` under the same membership lock when the recipient is not yet an owner.
   - `end_campaign_membership` stamps every revocation and the closure with one `clock_timestamp()` read after its locks. `now()` is the transaction start time; an end that queued behind a transfer stamped `revoked_at` earlier than the assignment the transfer had just created and failed the `revoked_at >= granted_at` check (a 400).

   **The recipient check (DEF-011).** `transfer_campaign_ownership` judges the recipient in four steps:

   1. **Lock already-expired rows.** With the caller's own owner assignment held, and before the recipient's membership row, it locks the recipient's unrevoked owner rows in this campaign that have expired by the statement's own clock (`expires_at <= clock_timestamp()`). This is the role-rows-then-membership order `end_campaign_membership` uses. Only expired rows are locked: a live recipient row is the other half of a mutual transfer's own lock, and locking it would deadlock the pair. `ux_membership_roles_active` allows at most one unrevoked owner row per membership, so this is at most one row.
   2. **Re-read after the waits.** After the relinquishing locks (membership, owner template, campaign), it reads one fresh `clock_timestamp()` and classifies the recipient's unrevoked owner rows in this campaign against it. `now()` is the transaction's start, so it would still call live a row that expired during a wait. A row expired at that instant and locked in step 1 is closed with `revoke_membership_role` and replaced. A row that expired *after* step 1 would have to be locked again after the recipient's membership, against the lock order, so the transfer is refused: 409 `ownership_transfer_recipient_changed`, nothing written, the caller keeps ownership. A retry then locks it in step 1 and replaces it.
   3. **"Already an owner" is the shared live-owner definition.** `find_live_builtin_owner_assignment(..., as_of=<that instant>)`: same campaign, active built-in role, assignment neither revoked nor expired, open active membership, active account. Anything short of that goes to `assign_membership_role`, whose eligibility checks refuse a recipient in another campaign (404), or with an ended or inactive membership or an inactive account (409). Before this, an unrevoked row on an inactive account or in another campaign counted as "already an owner", so the caller relinquished to a recipient who owned nothing here.
   4. **Final check at completion.** After the caller's own assignment is revoked, `_require_live_recipient_at_completion` checks the recipient once more at a new `clock_timestamp()` and refuses (same 409, rolled back) if they are no longer live. Before checking, it takes the key-share lock on the caller's account that the endpoint's audit row's foreign key would otherwise take afterwards. That is the same lock in the same position as before, so the lock order is unchanged, but its possible wait now happens before the check. The only other step before commit is the retention trigger's campaign row lock, which a relinquishing transfer already holds. So nothing waits between the final check and commit.

   **Concurrent writes to the recipient.** A relinquishing transfer holds three locks from before its recipient check until it commits, each blocking one kind of concurrent write:
   - a revocation of the recipient's owner row takes the campaign row at commit;
   - ending the recipient's membership needs the recipient's membership row;
   - deactivating the recipient's account needs that account row `FOR UPDATE`.

   A revocation, end or deactivation that committed earlier is seen by the check: the recipient is reassigned, or refused if ended or inactive. One still in flight cannot commit until the transfer has, so it applies afterwards, which is the serial order. That a later revocation, end or deactivation can still remove the last live built-in owner while a custom manager remains is the "left out on purpose" item below, not part of DEF-011. A non-relinquishing transfer gives nothing up, so a later change only makes its result older.

   **Recipient account deactivation.** These are the locks actually involved:
   - **Deactivation** (`_set_local_account_lifecycle_status_impl` in `commands/local_auth.py`, the only writer of `security.users.lifecycle_status_id`): a transaction advisory lock, then the target's account row `FOR UPDATE`, then the status update, then session revocation and the `status_changed` audit row.
   - **Audit row's foreign key** to `security.users` (`actor_user_id`): `FOR KEY SHARE` on the actor's account.
   - **Nested assignment** (`assign_membership_role`): the recipient's account `FOR UPDATE`, under the recipient's membership.
   - **Deferred retention trigger**: the campaign row `FOR UPDATE` at commit, already held by a relinquishing transfer.

   The relinquishing transfer takes the recipient's account `FOR KEY SHARE` after the recipient's membership and before the owner template, which is the account's position in the order above. Key share is the weakest lock that conflicts with `FOR UPDATE`, so it blocks deactivation. It is compatible with other key-share locks, so it does not recreate the mutual-transfer deadlock. It is also compatible with a login's `last_login_at` update (`FOR NO KEY UPDATE`). Both orders are pinned over HTTP, with audit and commit, in `test_campaign_owner_expired_recipient.py`. If the deactivation holds the row first, the transfer waits, sees the inactive account and is refused (409, the caller keeps ownership, no transfer audit). If the transfer is paused after its final check, at its audit insert, the deactivation waits for its commit and applies after it.

   **Time boundary (not closed by any lock).** Row locks serialize writes; they cannot stop a finite `expires_at` from passing. The final check proves the recipient was live at an instant after every lock wait and after the caller's revocation. When the recipient's live assignment has no expiry, that is enough. When it has a finite `expires_at`, it can pass between that instant and commit. Nothing waits there in normal operation (the remaining steps are the audit insert, whose locks are already held, and commit), but the interval is not zero. A probe that paused the transfer at its audit insert and let the assignment expire produced a committed `assigned: false, relinquished: true` handoff to an expired assignment and no live owner. So for a recipient with a finite assignment the guarantee was only "live at final validation", not "live at commit". Three policies were offered: (a) accept the boundary; (b) refuse a relinquishing transfer whose recipient's owner assignment has a finite `expires_at`, the standard the retention rule already applies to `access.manage`; (c) require a minimum remaining lifetime.

   **Caller's expiry during a lock wait (DEF-013).** The gate judges the caller at the transaction's start `now()` and locks the assignment, then the command waits on its other locks. A finite caller assignment can pass `expires_at` during those waits, so every gated command re-judges the caller with the shared predicate at a fresh `clock_timestamp()` (`_recheck_caller_is_live_owner`) after its last lock wait and before its first protected write. The assignment is already held (`FOR SHARE`, or `FOR UPDATE` for a relinquishing transfer), so the re-check takes no lock, cannot wait and leaves the lock order above unchanged. Where it runs:

   | Command | Re-check |
   |---|---|
   | `assign_membership_role` (owner role) | after the membership, account and role-template locks, before the INSERT |
   | `change_membership_role` (to owner) | after the row and new-role locks and the no-op check, before revoking the old row |
   | `add_campaign_member` (owner role) | after the campaign, account, identity and role locks, before creating the membership |
   | `transfer_campaign_ownership` | after the recipient locks and the recipient read, before closing the recipient's expired row; and again immediately before revoking the caller's own assignment, after `assign_membership_role` |

   A caller who is no longer live gets 403 `campaign_owner_required` with nothing written. When the second transfer check fails, the exception rolls back the recipient assignment made earlier in the same transaction, and the caller keeps ownership. The time-boundary paragraph above applies to the caller in the same way: an `expires_at` that passes after the last re-check, with no lock able to prevent it, is not closed.

   **Approved policy: option (b) (owner, 2026-11-06).** A relinquishing transfer requires the recipient to hold a live, *non-expiring* built-in owner assignment.
   - **Live, finite recipient row:** the transfer is refused before any write with 409 `ownership_transfer_recipient_assignment_expires`. This applies even when the row would still be live at final validation. Both assignments stay exactly as they were, no transfer audit is written, and the recipient's assignment is never extended or replaced.
   - **Recipient not yet an owner, or holding an already-expired row:** the existing assignment and replacement paths still apply, because `assign_membership_role` creates a row with no `expires_at`.
   - **Final check:** after the caller's revocation, the completion check requires the recipient's live row to be non-expiring as well (`require_non_expiring`). No command changes an existing assignment's `expires_at`.
   - **Non-relinquishing transfers** are unchanged: a live, finite recipient is reported as already an owner and nothing is written.

   With no expiry, and with revocation, membership end and deactivation all held off by the transfer's locks, a recipient who is live at the final check is still live at commit. Regressions: `test_a_relinquishing_transfer_to_a_live_finite_owner_assignment_is_refused` (the row is live for another hour; it failed on `0f8b3ab` with `assigned: false, relinquished: true`) and `test_a_non_relinquishing_transfer_to_a_live_finite_owner_is_unchanged`.

   Remaining, not changed here: `change_membership_role` locks its role row, membership and current role in one statement, whose internal order follows the query plan rather than a stated rule; it has always been so, and it follows the same role-row-then-membership order in practice.

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

Each is recorded in the [defect register](PHASE14_15_DEFECT_REGISTER.md) §9 with a proposed grading. F1 and F2 are checked by `scripts/preflight_campaign_owner_gate.py`. F1 is fixed; F2 and F3 are open.

- **F1 (DEF-011), expired-target transfer.** Fixed in a later checkpoint, then corrected after review: see the defect register and §3 ("The recipient check"). A transfer replaces a recipient's already-expired, unrevoked owner row with a live one. It counts a recipient as an existing owner only by the shared live-owner definition at a fresh database instant. It refuses atomically when the recipient's row expires during a lock wait, or when the recipient is not a live owner at completion. Under the approved policy (option b), a relinquishing transfer also refuses a recipient whose live owner assignment has a finite `expires_at`.
- **F3 (DEF-013), caller expiry during a lock wait.** Fixed in a later checkpoint: see the defect register and §3 ("Caller's expiry during a lock wait").
- **F2 (DEF-012), recovery gap.** `recover_campaign_access_manager` and the stranded-campaign report look for any non-expiring `access.manage` holder. When a custom role is the only `access.manage` holder and no live built-in owner exists, an administrator cannot restore an owner and the campaign permanently loses owner-derived reveal authority. Not reachable through an application path today (no endpoint writes custom role capabilities).

### A2a additions to the section 3 order (2026-11-07)

A2a adds two commands that read these rows and reverse none of the rows above (plan section 5.8, verified by `tests/database/test_character_public_profile_concurrency.py`):

- `release_character_public_profile` (since A2b-1 it takes the **world row `FOR SHARE`** first, ahead of everything below; no world `FOR UPDATE` taker takes any later row of the release before the world): the reveal-authority rows as `resolve_reveal_authority(lock="share")` takes them (owner assignment `S`, or the `gm` assignment `S` then the delegation row `S`) → the caller's membership `FOR SHARE` → the campaign `KEY SHARE` → the character's `core.entities` row `KEY SHARE` → the draft `FOR UPDATE` → fresh-instant re-judgement of the authority (the same source as the locked read, or `403 character_reveal_required`) → the whole-character deny re-resolved → write.
- `save_character_public_profile_draft`: `lock_authoring_scope` (P0/P1 order) → the `AccessContext` re-resolved → the character's entity `FOR SHARE` → the draft `FOR UPDATE` (or the unique-index wait of a first save).

## 8. Implementation record (2026-11-06)

- Shared check: `dnd_ai.domain.access.find_live_builtin_owner_assignment` (optional row lock; optional `as_of` instant for expiry, default the transaction's `now()`) and `is_builtin_campaign_owner_role`. The reveal resolver reuses the first. A caller that has waited on locks passes a fresh `clock_timestamp()` as `as_of`.
- Gate: `_require_builtin_campaign_owner` / `_require_owner_if_granting_owner_role` in `commands/memberships.py`, in `assign_membership_role`, `change_membership_role`, `add_campaign_member` and `transfer_campaign_ownership`. Refusal is `CampaignOwnerRequiredError`, 403 `campaign_owner_required`.
- Role list: `list_assignable_campaign_roles` takes the caller's membership and omits the built-in owner role unless the caller is a live owner.
- Preflight (local development database, read-only, 2026-11-06): all four counts zero (non-owner `access.manage` roles 0; live owner rows on ended or inactive memberships 0; expired unrevoked owner rows 0; active campaigns without a live owner 0).
- Not changed: schema, recovery, campaign creation, invitation acceptance, every non-owner role path.

### Reveal delegation (the second A1 change)

- **Migration `141_character_reveal_delegations`.** Inserts the `character.reveal` capability row (vocabulary only; the seed file stays frozen), creates `security.character_reveal_delegations` and adds a trigger to `role_capabilities`, `character_relationship_type_capabilities` and `resource_grants` that refuses any row naming `character.reveal`. Lossy, supported downgrade (drops the table, triggers and capability row). No backfill: nobody holds a delegation after the upgrade.
- **Table.** One row per grant, bound to the grantee's specific built-in `gm` assignment (`gm_membership_role_id`). Immutable: `campaign_id`, grantee, bound assignment, `granted_at`, `reason`. A scope trigger refuses a grantee, bound assignment or acting membership from another campaign, and a bound assignment that is not the built-in `gm` template's. A partial unique index allows one live row per grantee. Closing a row records `revoked_at` and an `end_reason` (`revoked_by_owner`, `gm_role_revoked`, `gm_role_changed`, `gm_assignment_lapsed`, `membership_ended`, `membership_status_changed`).
- **Resolver.** `dnd_ai.domain.reveal_authority.resolve_reveal_authority` returns `owner` (a live built-in owner assignment, `find_live_builtin_owner_assignment`), `delegation` (an unrevoked delegation whose bound row is exactly the member's live `gm` assignment, `find_live_builtin_gm_assignment`, which applies the owner predicate's liveness definition to the `gm` template) or `none`. A custom role, `canon.edit`, `access.manage` and assistant-GM status resolve to `none`.
- **Commands and routes.** `grant_character_reveal_delegation` and `revoke_character_reveal_delegation` (`commands/character_reveal.py`), `POST /campaigns/{id}/reveal-delegations` and `POST /campaigns/{id}/reveal-delegations/{grantee_membership_id}/revoke` (`api/character_reveal.py`), one audit row per actual change and none for a repeat. The route requires `access.manage` as a coarse filter; the command requires a live built-in owner (D3 gate, 403 `campaign_owner_required`) and re-checks the caller at a fresh instant after its last lock wait (DEF-013). A grantee without a live built-in `gm` assignment gets 409 `reveal_delegation_recipient_not_gm`; a membership of another campaign gets 404.
- **Lifecycle hooks** (`commands/reveal_delegation_lifecycle.py`): `revoke_membership_role` (`gm_role_revoked`), `change_membership_role` (`gm_role_changed`), `end_campaign_membership` (`membership_ended`) and `recover_campaign_access_manager`, when it changes a membership's status (`membership_status_changed`), close the delegation bound to what they change. Delegations a member *granted* are never closed by their loss of ownership (provenance, not authority).
- **Time lapse.** A `gm` assignment that expires without a command leaves its delegation unrevoked, with no authority (the resolver fails closed). A later grant to a newly eligible GM closes it with `gm_assignment_lapsed` before inserting, so a lapsed row never blocks a fresh grant. A second case is a `gm` assignment that a concurrent grant sees but does not lock (it was assigned after the grant's locks): the delegation can end up bound to an assignment revoked a moment later, again with no authority, and again closed by the next grant.
- **Transfer.** `transfer_campaign_ownership` is unchanged. Existing delegations survive it; the relinquishing owner loses owner-derived authority and keeps only a separate delegation bound to their own live `gm` assignment; the new owner may revoke what the former owner granted.
- **Locking.** Table in §3. Verified by `tests/database/test_character_reveal_delegation_deadlocks.py`; two deadlocks found in review of the first implementation are fixed, and an earlier claim that recovery cannot overlap a grant is withdrawn.
  - *Only the grantee's `gm` rows are locked* (not every role row): two owners delegating to each other would otherwise each hold the other's owner assignment `FOR SHARE` and want it `FOR UPDATE`.
  - *Reciprocal grants.* Owners A and B (both holding a live built-in `gm` assignment) grant each other at once. Each request locked its grantee's membership `FOR UPDATE`; the delegation insert's foreign key to `granted_by_membership_id` needs `FOR KEY SHARE` on the *other* request's grantee membership, which `FOR UPDATE` conflicts with. Each waited on the other (PostgreSQL aborted one with a 500). The grantee's membership is now locked `FOR NO KEY UPDATE`, which still excludes every command that takes the membership `FOR UPDATE` (`end_campaign_membership`, `assign_membership_role`, `change_membership_role`) and does not conflict with a key share. Both grants commit: two live delegations, two audit rows.
  - *Grant against administrative recovery.* `recover_campaign_access_manager` runs whenever no *non-expiring* access manager exists, so a live owner with a finite assignment can grant while it runs. Recovery locked the campaign row and then queued for the membership it promotes; a grant held that membership and wanted the campaign row `FOR UPDATE` (explicitly, and through the insert's foreign key). Two changes remove the cycle without reversing either command's order: the grant and revoke no longer take the campaign row `FOR UPDATE` (a grant takes it `FOR KEY SHARE`, the mode its foreign key needs anyway, before the re-check so a wait for it is still behind the re-check), and recovery takes the campaign row `FOR NO KEY UPDATE`, which excludes every other campaign-row `FOR UPDATE` taker (a second recovery, adding a member, a relinquishing transfer, the retention trigger at commit) and does not conflict with a key share. Recovery's eligibility is unchanged. The campaign-wide serialization of grants that the plan listed is not needed: the per-grantee `gm` rows, membership and delegation row, plus the one-live-row index, serialize every pair of operations that can conflict.
  - *What each mode still excludes.* Against `end_campaign_membership` and `revoke_membership_role` (role rows first, the same grantee rows next) the first lock on the grantee's `gm` rows decides the order; against a relinquishing transfer the caller's owner assignment (`S` against `U`) does; the transfer's `FOR UPDATE` on the campaign row makes a grant wait at its key share until the transfer commits, and the transfer waits for nothing a grant holds. Caller expiry during any of these waits is refused by the re-check, including a wait for the campaign row or the caller's membership (`test_a_grant_waiting_for_the_campaign_row_still_rechecks_the_caller_afterwards`, `test_a_revocation_waiting_for_the_callers_membership_still_rechecks_the_caller`).
  - *Harness.* The scenarios wait until PostgreSQL reports each request blocked by the holder's own session (following the chain of blockers: waiters on one row queue behind each other), report a request that finished before blocking instead of timing out, and release held locks on failure. They do not rely on a longer timeout.
- **Tests.** `tests/database/test_character_reveal_delegation.py` (policy boundaries, lifecycle, cross-campaign, transfer, and the races against GM role revocation, membership end, relinquishing transfer and a revocation of the delegation itself), `tests/database/test_character_reveal_delegations_migration.py`.
