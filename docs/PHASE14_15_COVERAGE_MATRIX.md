# Phase 14/15 coverage matrix (CP-11 restart)

Traceability from every original case and required variant to the guide task, evidence methods and ledger row. Written 2026-10-26 for `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`. **Nothing here is a result.** Retest class is from the integration plan §8 (F full rerun · T targeted · D defect retest · X expectation corrected · N not yet executed); the restart reruns every row regardless.

Evidence methods: **H** human/manual in the portal · **S** scripted real-browser (needs an owner login) · **D** database corroboration · **A** automated (representative modules named; never a case pass) · **X** accessibility/AT.

## 1. Original cases

| Case | Title | Class | Accepted change to the earlier expectation | Guide task | Methods | Ledger | Representative automated coverage |
|---|---|---|---|---|---|---|---|
| TC-01 | Administrator baseline and login return | T | Admin now admin+gm (system roles) | A1, A2, A3 | H, S, A | TC-01 | tests/database/test_api_auth, test_api_local_auth; portal LoginPage/App.landing |
| TC-02 | Live account permissions and campaign lists | F | GM2/`gm` no longer creates worlds (ADR 0020); roles from system-role table | A1, B2 | H, S, A | TC-02 | tests/database/test_api_campaigns, test_system_roles; portal App.scopedRoles |
| TC-03 | Hierarchy and stable Worlds navigation | T | Hierarchy re-verified after bootstrap change | J4 | H, S, A | TC-03 | portal App.contextPropagation, TimelinesPage tests |
| TC-04 | Campaign-derived world visibility and creation eligibility | F | Creation = system GM (+ use grant); GM no longer creates | B2, C1, D2 | H, S, A | TC-04 | tests/database/test_world_creation_policy, test_campaign_creation_authority, test_world_visibility |
| TC-05 | World categories, counts and browse-state persistence | T | Drafts need read_private | J4 | H, S, A | TC-05 | tests/database/test_api_world_explorer, test_world_explorer_canon_visibility; portal CampaignWorldPage.browse |
| TC-06 | Collapsed party disclosure | T | — | G4 | H, S, A | TC-06 | portal CharacterParties tests; tests/database/test_api_character_parties |
| TC-07 | Player Knowledge = character knowledge plus eligible parties | T | — | J3 | H, S, A | TC-07 | tests/database/test_api_knowledge_browse, test_knowledge_expansion; portal KnowledgePage tests |
| TC-08 | Public Knowledge, no character, timeline separation | T | — | J3 | H, S, A | TC-08 | tests/database/test_api_knowledge_browse |
| TC-09 | Member preview vs member's own view | T | Preview uses subject authority | J5 | H, S, A | TC-09 | tests/database/test_api_preview; portal App.knowledgeMemberPreview |
| TC-10 | Draft, archive, supersession and scope boundaries | X+T | AMENDED (DR-1): drafts 404; archived/superseded published readable by reference | K1 | H, S, A | TC-10 | tests/database/test_entity_lifecycle_commands, test_world_explorer_canon_visibility, ENTITY_LIFECYCLE 3.3 |
| TC-11 | Create isolated world, timeline and campaign | F | Setup requires system GM + world eligibility | C1, C2, E2, E3 | H, A | TC-11 | tests/database/test_api_worlds, test_api_timelines, test_api_campaigns; scenario test_phase14_authoring_flow |
| TC-12 | Setup cancellation and recovery | F | — | E1 | H, A | TC-12 | portal CampaignSetupPage tests |
| TC-13 | Enrol members, separate campaign roles | F | Invitations keep system roles; observer established; existing-account add path | E4, E5 | H, A | TC-13 | tests/database/test_api_campaign_invitations, test_api_memberships, test_api_access_overview; portal CampaignAccessPage tests |
| TC-14 | Calendar dates and world-time points | T | Calendar = world.manage; time points = campaign GM exception (E1) | C3, E6 | H, A | TC-14 | tests/database/test_calendars_and_world_times, test_api_world_time |
| TC-15 | Advance and correct the campaign clock | D+T | Optional cause + member-safe explanation (DR-4) | E7, I3 | H, A | TC-15 | tests/database/test_api_campaign_clock, test_api_clock_cause, test_clock_advance_details_migration; portal CampaignClockCard tests |
| TC-16 | Location types, hierarchy and reparenting | T | World Editor/Reviewer authority | F1, F2 | H, A | TC-16 | tests/database/test_api_location_authoring, test_phase7_reparent_guards |
| TC-17 | Organizations, subtype fields, religion references | T | World roles | F3 | H, A | TC-17 | tests/database/test_api_organization_authoring, test_organization_hierarchy_migration |
| TC-18 | NPC/PC identity, publishing, character relationships | T | PC creation/publish = campaign GM exception (E3) | F4, G1, G2 | H, A | TC-18 | tests/database/test_api_npc_authoring, test_api_player_character_authoring, test_api_character_relationships_reader |
| TC-19 | Immutable builds, starting state, activation | D+T | Activation explanation (CP-9a) | G3 | H, A | TC-19 | tests/database/test_api_character_builds, test_character_build_concurrency, test_api_event_explanations |
| TC-20 | Party create/edit, archive/restore | T | — | G4 | H, A | TC-20 | tests/database/test_api_parties, test_party_definition_migration |
| TC-21 | Temporal party membership, overlap | D+T | Join explanation (CP-9a) | G4 | H, A | TC-21 | tests/database/test_api_party_members, test_party_memberships, test_api_event_explanations |
| TC-22 | Schedule/edit sessions and participant preparation | D | Compatible roles, accurate rejection (CP-1); roster (CP-3); member roster (CP-8) | H1, J2, K7 | H, A | TC-22 | tests/database/test_api_session_play, test_api_session_authoring, test_api_session_member_roster; portal SessionRunPage tests |
| TC-23 | Staged Run Session navigation, unsaved inputs | T | Roster section present | H2 | H, A | TC-23 | portal App.sessionRun |
| TC-24 | Start session, world-time bar, public/private log | T | — | I1 | H, A | TC-24 | tests/database/test_api_session_play, test_session_play_concurrency |
| TC-25 | Manual event record, void and correction | D+T | Correction explanation + replacement variant (CP-9a) | I2 | H, A | TC-25 | tests/database/test_api_event_corrections, test_api_event_explanations; portal App.eventCorrections |
| TC-26 | Quest definition | T | World roles | H3 | H, A | TC-26 | tests/database/test_api_quest_authoring; portal QuestAuthoringPages tests |
| TC-27 | Quest runtime scopes, completion, correction | T | Runtime by campaign GM | I5 | H, A | TC-27 | tests/database/test_api_quest_runtime, test_api_quest_completion |
| TC-28 | Knowledge creation, guided navigation, unsaved claim edits | T | — | H4 | H, A | TC-28 | tests/database/test_api_knowledge_authoring; portal KnowledgeClaimPage tests |
| TC-29 | Claim review/publication, rejection, unpublished subject | T | Reviewer publishes | H4 | H, A | TC-29 | tests/database/test_supersession_publish_preconditions, test_api_entity_lifecycle |
| TC-30 | Party reveal, learning, telling, belief, public | T | — | I6 | H, A | TC-30 | tests/database/test_knowledge_reveal, test_api_knowledge_runtime, test_party_knowledge |
| TC-31 | Archived and superseded claims keep knowledge | X+D | AMENDED (DR-1/DR-5): archive browse; archived direct read | K2 | H, A | TC-31 | tests/database/test_api_knowledge_archive_browse; portal KnowledgePage tests |
| TC-32 | Claim Sources, separate keys, navigation guard | T | Source attach needs world edit | H4 | H, A | TC-32 | tests/database/test_api_sources, test_source_link_concurrency |
| TC-33 | Dungeon, areas, connections, content | T | — | H5 | H, A | TC-33 | tests/database/test_api_dungeon_authoring, test_dungeon_structures |
| TC-34 | Dungeon runtime state and correction | T | Area now = campaign projection | I7 | H, A | TC-34 | tests/database/test_api_dungeon, test_area_runtime_projection, test_dungeon_state_event_migration |
| TC-35 | Relationships and participant perspectives | T | Definitions (world) vs runtime (campaign) | G6 | H, A | TC-35 | tests/database/test_api_relationship_authoring, test_api_relationships |
| TC-36 | Organization members, offices, operational status | T | — | G7 | H, A | TC-36 | tests/database/test_api_organization_members, test_api_organization_reader |
| TC-37 | Routes and travel | T | Fresh session; clock untouched | H6, I4 | H, A | TC-37 | tests/database/test_api_routes_travel, test_api_session_travel, test_travel_concurrency |
| TC-38 | NPC portrayal, runtime, privacy | T | Resource positive variant Blocked | H9, I9 | H, A | TC-38 | tests/database/test_api_npc_portrayal, test_npc_portrayal_concurrency |
| TC-39 | World-owned item definitions, generic seed protection | T | World-gated | H7 | H, A | TC-39 | tests/database/test_api_item_definitions |
| TC-40 | Item instances: award, transfer, equip, custody | D+T | Instance exception; owner inventory via character nav (CP-5) | H8, I8, G5 | H, A | TC-40 | tests/database/test_api_items, test_api_item_runtime, test_api_characters_inventory |
| TC-41 | Item quantity, damage/repair, attunement, destruction | N | Fresh Charm/session | I8 | H, A | TC-41 | tests/database/test_api_item_runtime, test_item_runtime_concurrency, test_api_item_corrections |
| TC-42 | Encounter preparation and compact roster | N | Roster identity retest | H10 | H, A | TC-42 | tests/database/test_api_encounter_preparation; portal EncounterPages tests |
| TC-43 | Operate an encounter | N | — | I10 | H, A | TC-43 | tests/database/test_api_encounter_operations, test_encounter_operation_concurrency |
| TC-44 | Discard pending, abort active | N | — | I10 | H, A | TC-44 | tests/database/test_api_encounters, test_encounter_domain |
| TC-45 | Sources and provenance across typed records | N | Explicit source links | H11 | H, A | TC-45 | tests/database/test_api_sources, test_entity_source_links_migration |
| TC-46 | Revision history and comparison | N | — | J6 | H, A | TC-46 | tests/database/test_entity_revisions |
| TC-47 | Review queue and lifecycle transitions | N | Editor/Reviewer split | J7 | H, A | TC-47 | tests/database/test_api_review_queue, test_entity_lifecycle_commands |
| TC-48 | Validation, stale writes, retry, no-store | N | CP-2 receipt/refresh behaviour | K5 | H, S, A | TC-48 | tests/database/test_actor_idempotency, test_authoring_concurrency; portal useAuthoringMutation tests |
| TC-49 | Plain-player denial matrix | N | Regenerated route manifest incl. new surfaces | J9, K3 | H, S, A | TC-49 | tests/scenario/phase15_route_manifest.py, test_phase15_acceptance_guards |
| TC-50 | End session, review, read-only, archive/restore | N | Roster on completed detail (CP-3/CP-8) | I11, J1, J2 | H, A | TC-50 | tests/database/test_api_session_play, test_session_chronology |
| TC-51 | Campaign, timeline, world archive/restore guards | N | Separated world/campaign authority | K4 | H, A | TC-51 | tests/database/test_api_campaign_lifecycle, test_timeline_reuse_lifecycle |
| TC-52 | Timeline branch boundaries | N | Branch by Owner/Editor | K3 | H, A | TC-52 | tests/scenario/test_branch_creation_history, test_branch_effective_history |
| TC-53 | Explicit world_viewer without campaign membership | N | Sharing UI replaces operator script; Viewer != Reader | Companion 5 | H, A | TC-53 | tests/database/test_world_viewer_role_migration, test_world_sharing, test_world_reader_canon |
| TC-54 | CSRF, signed-out requests, current authority | N | World-role / use-grant / system-GM revocation on next request | K6 | H, S, A | TC-54 | tests/database/test_scoped_roles_concurrency, test_api_deps, test_api_cors |
| TC-55 | Responsive, keyboard, screen-reader, zoom, reduced-motion | N | Final layouts incl. new screens | Companion 6 | H, X | TC-55 | portal jsdom tests only (cannot substitute) |
| TC-56 | Clean-deployment walkthrough | N | Bootstrap admin = admin+gm; explicit role + relationship | Companion 7 | H, S*, A | TC-56 | tests/scenario/test_phase15_completion_flow, test_scoped_roles_flow |
| TC-57 | Manual privacy evidence: audit, receipts, reporting role | N | No secrets in artefacts | J8 | H, D, A | TC-57 | tests/database/test_private_data_not_stored, test_reporting_role_boundary, test_scrub_replay_and_future_writes |
| TC-58 | Targeted claim grants/denies and preview agreement | N | Allow never yields world authority | K8 | H, S, A | TC-58 | tests/database/test_api_access_grants, test_resource_grant_target_column |

`S*` TC-56: scripted evidence is possible only after the owner bootstraps the clean installation's administrator.

## 2. Variants and amended expectations

| Ledger id | Parent | Variant / amended expectation | Guide task | Persona |
|---|---|---|---|---|
| 02.gm | TC-02 | `gm` campaign list/capabilities: none yet, then after E4 | B2/E4 | gm |
| 02.player_a | TC-02 | `player_a` lists and perspectives | B2/G2 | player_a |
| 02.player_b | TC-02 | `player_b` lists and perspectives | B2/G2 | player_b |
| 02.observer | TC-02 | `observer` lists, no perspective | B2/E4 | observer |
| 02.disabled | TC-02 | `disabled` safe login refusal | A3 | disabled |
| 04.gm-no-create | TC-04 | `gm` (Player only) gets no World create form | B2 | gm |
| 10.draft | TC-10 | Draft definition = same 404 as missing for a player (amended) | K1 | player_a |
| 10.archived | TC-10 | Archived/superseded published readable by reference (amended) | K1 | player_a |
| 10.cross-scope | TC-10 | Same-world other-timeline records unreadable; foreign campaign refused | K3 | admin, player_a |
| 15.manual | TC-15 | Plain manual advance + correction (E7) | E7 | gm |
| 15.cause | TC-15 | Optional cause + member-safe explanation (CP-9b) | I3 | gm, player_a, observer |
| 15.runtime-no-world-role | TC-15 | Runtime GM advance without world role (SR-M8) | Companion SR-M8 | gm |
| 19.explain | TC-19 | Build-activation event explanation by audience (CP-9a/DR-6) | G3 | gm, player_a, observer |
| 19.other-characters | TC-19 | Hero B / NPC starting state and builds | G3 | gm |
| 21.explain | TC-21 | Join/leave explanation (CP-9a) | G4 | gm, players |
| 21.leave-rejoin | TC-21 | Tobin leaves and rejoins | G4 | gm |
| 21.npc-reserve | TC-21 | NPC membership of Reserve | G4 | gm |
| 22.roles | TC-22 | Compatible roles, accurate rejection, no Guest default for PC (CP-1) | H1 | gm |
| 22.roster-gm | TC-22 | Roster section on session detail/run/review (CP-3) | H1/H2 | gm |
| 22.member-pc | TC-22 | Member roster: player with related PC (CP-8) | J2 | player_a |
| 22.member-npc | TC-22 | Member roster: discoverable NPC link rules | J2 | player_a, player_b |
| 22.member-undiscovered | TC-22 | Undiscovered NPC absent, no hidden count (API-ONLY grant) | K7 | player_a, player_b |
| 22.member-observer | TC-22 | Member roster: observer | J2 | observer |
| 25.wrong-title | TC-25 | 'Wrong title' correction replacement variant (CP-9a) | I2 | gm, player_a |
| 25.void | TC-25 | Void with confirm/cancel | I2 | gm |
| 31.browse | TC-31 | Archive browse Active/Archived/All, eligibility, paging (CP-7) | K2 | gm, player_a |
| 31.archived-direct | TC-31 | Archived claim direct read by audience member (DR-1) | K2 | player_a |
| 31.supersede | TC-31 | Supersede, replacement inherits no knowers | K2 | gm |
| 38.resource-positive | TC-38 | Positive NPC resource adjustment (no supported fixture) — expected Blocked | I9 | gm |
| 38.resource-refusal | TC-38 | Missing tracked-resource refusal | I9 | gm |
| 40.owner-inventory | TC-40 | Owner inventory reachable via character nav (CP-5) | G5/I8 | player_a |
| 40.viewer-inventory | TC-40 | Viewer inventory-only view (CP-6) | Companion SR-M15 | observer |
| 49.01 | TC-49 | Location/organization/religion authoring routes | J9 | player_a |
| 49.02 | TC-49 | NPC/PC/builds/portrayal routes | J9 | player_a |
| 49.03 | TC-49 | Party management routes | J9 | player_a |
| 49.04 | TC-49 | Session/encounter operation routes | J9 | player_a |
| 49.05 | TC-49 | Events/quest operation routes | J9 | player_a |
| 49.06 | TC-49 | Knowledge authoring/management routes (legacy redirects to read-only claim) | J9 | player_a |
| 49.07 | TC-49 | Dungeon authoring routes | J9 | player_a |
| 49.08 | TC-49 | Items/definitions routes | J9 | player_a |
| 49.09 | TC-49 | Sources/revisions/review routes | J9 | player_a |
| 49.10 | TC-49 | Time authoring route | J9 | player_a |
| 49.11 | TC-49 | New surfaces: Sharing, world edit, Platform accounts | J9 | player_a |
| 49.observer | TC-49 | Representative denied routes as observer | J9 | observer |
| 49.signed-out | TC-49 | Representative denied routes signed out | J9 | signed-out |
| 49.foreign | TC-49 | Foreign campaign (branch campaign) and nonexistent campaign | K3 | player_a |
| 50.completed | TC-50 | Completed/archived read-only; archive/restore | J1 | gm, player_a |
| 50.roster | TC-50 | Member roster on the completed detail | J2 | players |
| 54.csrf | TC-54 | Missing/invalid CSRF, foreign Origin, signed-out 401 | K6 | gm |
| 54.campaign-role | TC-54 | Campaign GM role revoked before next request | K6 | gm, admin |
| 54.world-role | TC-54 | World Editor role ended before next request | K6 | gm, admin |
| 54.use-grant | TC-54 | Use-grant / system-GM revocation on next request | Companion SR-M6/M7 | admin |
| 57.receipts | TC-57 | Typed-content receipts minimal | J8 | admin |
| 57.audit | TC-57 | Audit/replay bodies hold no narrative markers (DB read-only) | J8 | admin |
| 57.sensitive-read | TC-57 | Metadata-only sensitive_read audit entries | J8 | admin |
| 57.reporting-role | TC-57 | Reporting role allowlist boundary (DB read-only) | J8 | admin |
| 58.allow | TC-58 | Targeted canon allow (API-ONLY) | K8 | observer |
| 58.deny | TC-58 | Targeted view deny (API-ONLY) and preview agreement | K8 | player_a |
| 58.revoke | TC-58 | Revocation restores projection | K8 | observer, player_a |
| T56-01 | TC-56 | Clean-install walkthrough step 1 (separate DB) | Companion 7 | admin, manual.player |
| T56-02 | TC-56 | Clean-install walkthrough step 2 (separate DB) | Companion 7 | admin, manual.player |
| T56-03 | TC-56 | Clean-install walkthrough step 3 (separate DB) | Companion 7 | admin, manual.player |
| T56-04 | TC-56 | Clean-install walkthrough step 4 (separate DB) | Companion 7 | admin, manual.player |
| T56-05 | TC-56 | Clean-install walkthrough step 5 (separate DB) | Companion 7 | admin, manual.player |
| T56-06 | TC-56 | Clean-install walkthrough step 6 (separate DB) | Companion 7 | admin, manual.player |
| T56-07 | TC-56 | Clean-install walkthrough step 7 (separate DB) | Companion 7 | admin, manual.player |
| T56-08 | TC-56 | Clean-install walkthrough step 8 (separate DB) | Companion 7 | admin, manual.player |
| T56-09 | TC-56 | Clean-install walkthrough step 9 (separate DB) | Companion 7 | admin, manual.player |
| T56-10 | TC-56 | Clean-install walkthrough step 10 (separate DB) | Companion 7 | admin, manual.player |
| T56-11 | TC-56 | Clean-install walkthrough step 11 (separate DB) | Companion 7 | admin, manual.player |
| T56-12 | TC-56 | Clean-install walkthrough step 12 (separate DB) | Companion 7 | admin, manual.player |
| T56-13 | TC-56 | Clean-install walkthrough step 13 (separate DB) | Companion 7 | admin, manual.player |
| T56-14 | TC-56 | Clean-install walkthrough step 14 (separate DB) | Companion 7 | admin, manual.player |
| T56-15 | TC-56 | Clean-install walkthrough step 15 (separate DB) | Companion 7 | admin, manual.player |
| T56-16 | TC-56 | Clean-install walkthrough step 16 (separate DB) | Companion 7 | admin, manual.player |

## 3. Scoped-role, recovery, navigation and privacy scenarios

| Ledger id | Scenario | Where |
|---|---|---|
| SR-M1 | Admin creates GM-only account; GM signs in | Companion §1 |
| SR-M2 | Admin-only account | Companion §1 |
| SR-M3 | Populated-upgrade identities (accounts-only baseline) | Companion §1 |
| SR-M4 | Editor vs Reviewer vs both | Companion §1 |
| SR-M5 | Reader vs Viewer | Companion §1 |
| SR-M6 | Use-grant hosting | Companion §1 |
| SR-M7 | Revoke then restore system GM from an Owner | Companion §1 |
| SR-M8 | Campaign-only GM in a shared world | Companion §1 |
| SR-M9 | Same person GM in A, Player in B | Companion §1 |
| SR-M10 | Invitation and account split | Companion §1 |
| SR-M11 | World and campaign ownership transfer | Companion §1 |
| SR-M12 | Stranding and recovery | Companion §1 |
| SR-M13 | Permission loss mid-edit | Companion §1 |
| SR-M14 | Offline upgrade with a stale tab (expected Blocked) | Companion §1 |
| SR-M15 | Viewer inventory | Companion §1 |
| SR-M16 | Character record navigation | Companion §1 |
| RC-01 | Validation refusal retains input | Companion §2 |
| RC-02 | Stale version, Load latest | Companion §2 |
| RC-03 | Uncertain retry keeps original payload and key | Companion §2 |
| RC-04 | Quest command confirmed, re-read fails | Companion §2 |
| RC-05 | Item operation/definition edit, re-read fails | Companion §2 |
| RC-06 | Claim save, detail read fails | Companion §2 |
| RC-07 | Claim lifecycle step, read-back fails | Companion §2 |
| RC-08 | Receipt-version gating, read-only recovery | Companion §2 |
| RC-09 | Independent drafts, record changes, late responses | Companion §2 |
| RC-10 | Callers fixed for DEF-001 (26 operations; retest on the reviewed head) | Companion §2 |
| NV-01 | Deep links | Companion §3 |
| NV-02 | Section links | Companion §3 |
| NV-03 | Breadcrumbs | Companion §3 |
| NV-04 | Back/Forward and reload | Companion §3 |
| NV-05 | Preserved filters and return context | Companion §3 |
| NV-06 | World / Characters / Items entry paths | Companion §3 |
| NV-07 | Focus after navigation | Companion §3 |
| NV-08 | Permission-loss fallback focus | Companion §3 |
| PV-01 | Platform authority (UI + data) | Companion §4 |
| PV-02 | World authority | Companion §4 |
| PV-03 | Campaign authority and foreign campaign | Companion §4 |
| PV-04 | Ownership and inventory | Companion §4 |
| PV-05 | Targeted deny and preview agreement | Companion §4 |
| PV-06 | Revocation and unavailable records | Companion §4 |
| PV-07 | Member-safe rosters, history, explanations, clock details | Companion §4 |
| PV-08 | No legacy private-text disclosure | Companion §4 |

## 4. CP-5 … CP-10 additions

| Checkpoint | Scenario | Guide task / companion | Ledger |
|---|---|---|---|
| CP-1 | Compatible participant roles, accurate rejection | H1 | 22.roles |
| CP-2 | Receipt vs refresh outcome; read-only recovery | RC-03…08, K5 | RC-03…RC-08 |
| CP-3 | Shared session roster on detail/run/review | H1, H2 | 22.roster-gm |
| CP-4 | Scoped roles: system / world / campaign / use grants | B2, D2, E4, SR-M1…M13 | SR-M*, 04, 13 |
| CP-5 | One character record; inventory reachable | G5, SR-M16 | 40.owner-inventory, SR-M16, NV-06 |
| CP-6 | Inventory-only viewer (`character.view_inventory`) | SR-M15 | 40.viewer-inventory, SR-M15 |
| CP-7 | Archived Knowledge browsing; archived direct read | K1, K2 | 31.browse, 31.archived-direct, 10.archived |
| CP-8 | Member-safe session roster; no hidden counts | J2, K7 | 22.member-*, 50.roster |
| CP-9a | Event explanations (party join, build activation, clock, correction) | G3, G4, I2, I3 | 19.explain, 21.explain, 25.wrong-title, 15.cause |
| CP-9b | Optional clock cause + member-safe explanation | I3 | 15.cause |
| CP-10 | Confirmed-write/failed-refresh for quest, item, claim; shared plumbing | RC-04…RC-07; RC-10 for the deferred callers | RC-04…RC-10, NV-* |
| DEF-001 fix (candidate `7990225…`, not frozen) | The same contract for every other write that reads its result back (26 operations: [RC-10 operation inventory](#rc-10-operation-inventory)) | RC-10 (rewritten); retest set in the environment document §9.2 | RC-03…RC-10, TC-14/15/19/20/21/24/25/33/34/35/36/37/38/42/43/44/50/51/53 and the lifecycle-step rows; **no human row executed**. Scripted browser retest on the reviewed candidate `38d2865…` (2026-10-26): RC-03…RC-09 and the exercised variants of all 26 operations pass except DEF-005 (reproduced) and DEF-006 (RC-06 authoring-read variant); remaining coverage per operation in [PHASE15_DEF001_BROWSER_RETEST.md](PHASE14_15_ACCEPTANCE_LEDGER.md) §3; candidate not frozen |

## 5. Reverse index — guide task to cases

| Task | Cases / scenarios |
|---|---|
| A1 | 01 02 SR-M3 |
| A2 | 01 54 |
| A3 | 01 02 |
| B1 | SR-M3 SR-M2 |
| B2 | 02 04 SR-M1 SR-M2 |
| C1 | 11 04 SR-M1 |
| C2 | 11 |
| C3 | 14 |
| C4 | 11 52 |
| D1 | SR-M5 SR-M6 |
| D2 | SR-M4 04 |
| E1 | 12 |
| E2 | 11 SR-M6 |
| E3 | 11 05 |
| E4 | 13 SR-M10 02 |
| E5 | 13 57 |
| E6 | 14 SR-M8 |
| E7 | 15 |
| F1 | 16 10 05 |
| F2 | 16 |
| F3 | 17 |
| F4 | 18 57 |
| G1 | 18 |
| G2 | 18 02 |
| G3 | 19 CP-9a |
| G4 | 20 21 06 CP-9a |
| G5 | CP-5 SR-M16 40 |
| G6 | 35 |
| G7 | 36 |
| H1 | 22 CP-1 CP-3 |
| H2 | 23 |
| H3 | 26 |
| H4 | 28 29 32 |
| H5 | 33 |
| H6 | 37 |
| H7 | 39 |
| H8 | 40 |
| H9 | 38 |
| H10 | 42 |
| H11 | 45 32 |
| I1 | 24 |
| I2 | 25 CP-9a |
| I3 | 15 CP-9b |
| I4 | 37 |
| I5 | 27 |
| I6 | 30 |
| I7 | 34 |
| I8 | 40 41 |
| I9 | 38 |
| I10 | 43 44 |
| I11 | 50 |
| J1 | 50 |
| J2 | 22 50 CP-8 |
| J3 | 07 08 |
| J4 | 05 03 |
| J5 | 09 |
| J6 | 46 |
| J7 | 47 |
| J8 | 57 |
| J9 | 49 |
| K1 | 10 |
| K2 | 31 CP-7 |
| K3 | 52 49 |
| K4 | 51 |
| K5 | 48 |
| K6 | 54 SR-M13 |
| K7 | 22 CP-8 |
| K8 | 58 |

## 6. Gaps, substitutions and cases that cannot be fully exercised

| Item | Disposition |
|---|---|
| TC-38 positive NPC resource spend/restore | **Blocked by design** (`38.resource-positive`): no supported pre-tracked NPC fixture. Do not insert a row by SQL or claim a pass from the refusal. |
| TC-31 deprecated-claim state | No supported way to create a deprecated claim; record **Blocked** unless the owner supplies one. |
| TC-41 full attunement-limit setup | Exercises one attune/transfer/end cycle; the limit-exceeded case needs several attuned items — record separately or **Blocked**. |
| TC-22 undiscovered participant, TC-58 grants, TC-48 replay | Need **API-ONLY** requests (documented UI gaps); listed on the task and in the ledger as API-ONLY. |
| SR-M14 stale tab across an upgrade | **Blocked**: rehearsed at the 2026-10-25 landing; not repeatable on a database that starts at 140. |
| Original TC steps that named dev fixtures (Dev A/B, Character A/B, Testing Session 3, etc.) | Replaced by The Saltmarch content; each task states the equivalent. Tester notes any substitution (plan DR-8). |
| TC-02 "revoked memberships absent", TC-21 "Player B owns Campaign B" | The old dev-campaign state no longer exists in the accounts-only baseline; the equivalents are E4/G2/G4 and SR-M9. |
| TC-53 operator script | Replaced by the **Sharing** UI (`observer` → Viewer on Empty Marsh). |
| Scripted real-browser evidence for the imported accounts | **Blocked pending owner login** — no credential was invented or reset (see environment doc §7). |

## 7. Proposed P02 navigation variants (added 2026-11-04 by P02-8)

Proposed by plan §8 (P02-8). **All four are marked *not executed*: no browser, scripted-browser, human or owner run has been performed for them.** Representative automated coverage (jsdom) is named for traceability only and is not evidence for these variants. Method codes as in the legend above.

| Variant | Title | Scope | Methods | Status | Representative automated coverage |
|---|---|---|---|---|---|
| 03.nav-split | Navbar split controls, menu and drawer lifecycle | Main control vs disclosure, menu open/dismiss, focus to first child, modified-link activation, narrow drawer, collapsed rail, touch | H, S, A | **Not executed** | portal `NavbarMenu.integration`, `PortalSidebar`, `navbarDestinations` tests |
| 05.task-origin | Breadcrumb and task origin across families | Hierarchy, task starts, direct entry, legacy adapters, wrapping at 320 px, 200% zoom and 400% zoom, screen-reader landmark and `aria-current` | H, S, A | **Not executed** | portal `breadcrumbModel`, `taskOrigin`, per-family `App.*Navigation` tests |
| 23.history | History retention and restoration | Back/Forward, reload, new tab, bfcache, `history.state` retention of `task` and `ctx` | H, S, A | **Not executed** | portal `selectedContext.history.integration`, `entryStamp` tests |
| 55.context-guard | Selection departure, guards and loss handling | Dirty Stay/Leave, native modal close, destination-heading focus, immediate and deferred arrival, announcements, withdrawal after authority loss, two-tab revocation | H, S, A | **Not executed** | portal `selectionDeparture.integration`, `selectionArrival*` tests |

The actionable [B1–B22 checklist](PHASE14_15_COMPANION_SCENARIOS.md#p02-browser-checklist) is a specification. Current per-check results and the explicit P02 owner decision are in the [ledger](PHASE14_15_ACCEPTANCE_LEDGER.md#current-decision-summary-after-documentation-reconciliation); the original “all not executed” wording is historical. DOM/live-region inspection is not screen-reader evidence.

## Consolidated specification and evidence sources

All TC-01–TC-58 IDs and variants above retain their original meaning and source history.
The retired manual guide is available as an immutable specification/evidence baseline in
[delivery history](DELIVERY_HISTORY.md); its historical result markings are not new passes.
Use the accepted expectation corrections in this matrix and the current journey/scenarios
when executing a new run. If an old step is not represented by a current task, retain it
as an explicit unexecuted variant rather than silently dropping it.

TC-55's complete former page/panel matrix, staged Run Session and Knowledge requirements,
Member preview, travel, Relationships and Organization checks are retained in
[companion scenarios](PHASE14_15_COMPANION_SCENARIOS.md#tc-55-page-and-panel-obligations).
The former manual matrix's date/tester, browser/AT version, failures/fixes, accepted risks,
final-head CI and owner completion decision must be recorded in the acceptance ledger.

### RC-10 operation inventory

The inventory below retains the DEF-001 operation numbering, intentional differences and
regression-test mapping. Its before/after descriptions are the historical fix baseline;
they do not certify today's callers. A tested variant never implies every command passed.

## 4. Inventory

Legend — **Reads**: what must be read back for the screen to agree with the write. **Result**: *Corrected*, *Compliant (reference)*, *Compliant (by design)* or *Retained difference*.

### 4.1 Corrected

| # | Operation (caller) | Reads | Behaviour before | Correction | Tests |
|---|---|---|---|---|---|
| 1 | World archive / restore (`TransitionControls` in `WorldOverviewPage`) | the world | `await refetch()`, outcome dropped; "World archived" announced; failed read replaced the page by "could not be loaded" | Returns the outcome; record kept (`useKept`); saved notice with read-only **Load latest**; transition held while stale; "done" announced when a read completes | `pages/WorldOverviewPage.test.tsx` (confirmed archive + failed read) |
| 2 | Timeline archive / restore (`TransitionControls` in `TimelinePage`) | the timeline | same | same | `pages/timelinePages.test.tsx` |
| 3 | Party archive / restore (`PartyRow` in `PartyPages`) | the party list | outcome dropped; archived row's state shown stale; failed read → error screen | outcome returned; list kept; row held; page announces when the list is read (the row may be gone) | `App.parties.test.tsx` |
| 4 | Party member end (`MemberTable` in `PartyMembersPage`) | the roster (party version) | same | outcome returned; roster kept; end and add held (party version); notice; recovery | `App.partyMembers.test.tsx` |
| 5 | Party member add (`AddMemberForm`) | the roster | same | same; **uncertain retry** keeps body and key | `App.partyMembers.test.tsx` (confirmed + failed read; lost answer then retry) |
| 6 | NPC portrayal save new version (`NpcPortrayalPage`) | the portrayal (versions) | outcome dropped; "not found" screen on a failed read; form re-keyed | outcome; portrayal kept; draft kept; both portrayal writes held; page announces on recovery (form is re-keyed) | `App.npcPortrayal.test.tsx` |
| 7 | NPC detail level | same | same | same | `App.npcPortrayal.test.tsx` |
| 8 | Character starting state (`StateSection`) | the builds listing | outcome dropped; error screen | outcome; listing kept; form held until read | `App.characterBuilds.test.tsx` |
| 9 | Activate a build (`BuildList`) | the builds listing | same | outcome; held (names the active build it showed) | `App.characterBuilds.test.tsx` |
| 10 | Event void / correct (`Corrections` in `EventPages`) | the event **and** the correction preview | two awaits, both outcomes dropped; "does not exist" screen on a failed read | both reads combined; both kept; actions held; page announces on recovery (the form is replaced by the correction) | `App.eventCorrections.test.tsx` (event read fails; preview-only fails) |
| 11 | World Sharing: assign / end role, grant / revoke use, transfer ownership (`WorldSharingPage`) | the access list | outcome dropped; any failed read → "Sharing is not available" | outcome; list kept; controls held; transfer's **denied** read is an authoritative answer (removes the content, focus to heading, "Ownership transferred" still announced) | `pages/WorldSharingPage.test.tsx` |
| 12 | Session Start (`StartControl`, `SessionRunPage`) | the session (version) | `await refetch()`; "Session started" and the log link shown after a failed read | not done until read; Start held; page announces and shows the link when the session is read | `App.sessionRun.test.tsx` |
| 13 | Session End (`EndControl`) | the session | same | same | `App.sessionRun.test.tsx` |
| 14 | Session log entry (`LogSection`) | the session | returned the outcome but showed no notice and never announced on recovery | notice beside the form; recovery announces | `App.sessionRun.test.tsx` |
| 15 | Travel (`TravelSection`) | the session's travel history | outcome dropped; "do not record again" only when the page was already stale | outcome; saved notice (receipt text) with read-only retry; a journey that moved no one reads nothing (intentional) | `components/TravelSection.test.tsx` (failed; superseded) |
| 16 | Campaign clock advance / correct (`CampaignClockCard`) | the clock (version, last event) | outcome dropped; card vanished on a failed read | outcome; clock kept; Advance/Correct held; notice | `components/CampaignClockCard.test.tsx` |
| 17 | Session details save (`SessionDetailPage`) | the session | "Session saved" announced after a failed read; Save not held; **Load latest** reset the stale notice even when its read failed | announced only when read; Save held until **Reload session**; stale reset only on success | `App.sessionAuthoring.test.tsx` |
| 18 | Session archive / restore (`SessionLifecycleControls`) | the session | outcome dropped | outcome; notice with read-only **Load latest** (no page retry exists); actions held | `App.sessionAuthoring.test.tsx` |
| 19 | Encounter commands: update, add / change / remove participant, start, abort, record turn, end (`PreparedEncounterPage`) | the encounter | outcome dropped; "does not exist" screen on a failed read | outcome; encounter kept; every command held (a turn could be recorded twice from the old view); page announces on recovery | `pages/EncounterPages.test.tsx` (start; turn) |
| 20 | NPC runtime: hit points, conditions, resources, move (`NpcRuntimePanel`) | the character | outcome dropped | outcome; panel keeps the numbers it read; all four held (they are deltas); notice | `components/NpcRuntimePanel.test.tsx`; `WorldRecordWorkspace.runtime.test.tsx` |
| 21 | Dungeon / area commands via `useDungeonCommand` (Areas, Connections, Contents, Area now) | the dungeon or area, its lifecycle and revisions (+ the record for Area now) | `reload()` returned nothing; `await refetch()` dropped; commands could repeat from a stale version | `reload()` returns an outcome (`usePairedRead`, `useAreaRuntimeRead`); the workspace's refresh functions combine only the reads that record makes; handle exposes `savedNotice` (rendered outside the form that closes) and holds commands; `clear()` no longer lifts the hold | `WorldRecordWorkspace.areaNow.test.tsx` |
| 22 | Lifecycle steps (`EntityLifecyclePanel` provider: World record, Item, Quest; Claim keeps its own page notice via `pageReportsRefresh`) | the lifecycle **and** the page's reads | the lifecycle read's outcome was dropped; Quest and Item `onChanged` returned nothing | combined; "done" only on `ok`; saved notice beside the actions; steps held; recovered when the lifecycle read works again | `WorldRecordWorkspace.test.tsx`; `QuestWorkspace.test.tsx` |
| 23 | Relationship add (`RelationshipsPanel`) and edit / perspectives / end / archive (`RelationshipEditor`) | the roster list and the relationship | decided "refreshed" from a shared ref (`refreshOk`), which a superseded read leaves untouched; reported `success` to the mutation | decided from the returned outcomes; mutation reports `confirmed`; a form whose relationship read failed holds its version-checked save | `components/RelationshipsPanel.test.tsx` |
| 24 | Organization: add member, set status, member editor (`OrganizationMembers`, `OrganizationMemberEditor`) | the roster | `void refetch()`; "Member added" / "Organization status saved" announced immediately | roster read awaited; announced only when read; roster-level saved notice (forms close); status and add held | `components/OrganizationMembers.test.tsx`; `WorldRecordWorkspace.runtime.test.tsx` |
| 25 | World time recorded inline (`WorldTimePicker`, used by party, session, clock, event and organization forms) | the world-time list | `refetch().then(...)` selected the id regardless; a failed read replaced the picker by an error | picker kept; new time chosen only once the list shows it; record-again held; read-only **Load latest** | `components/authoring/WorldTimePicker.test.tsx` |
| 26 | World time recorded (`WorldTimesPage`) | the list | announced "World time recorded" regardless; error screen | outcome; list kept; notice | `pages/WorldTimesPage.test.tsx` |

### 4.2 Compliant (reference implementations; not changed)

| Operation | Why it is compliant |
|---|---|
| Quest commands, details, structure editor, dependencies / outcomes / participants, progress (`useQuestCommand`, `QuestDetailsSection`, `QuestEditor`, `QuestProgressPanel`) | CP-10: return the (combined) outcome; announce on `ok` only; page-level kept data and retry |
| Item operations and item definition edit (`useItemOperation`, `ItemDefinitionPages`) | CP-10 |
| Knowledge claim save, audience, lifecycle read-back (`KnowledgeClaimPage`, `KnowledgeRoster`) | CP-10 (+ review follow-ups). Only the lifecycle provider's `refetch` now returns its outcome and the page passes `pageReportsRefresh`, so the panel does not add a second notice |
| Entity sources attach / detach (`EntitySourcesSection`) | CP-10 |
| Campaign settings save and archive; archived campaigns reactivation; shared content edit page | CP-2 |
| Session participants add / remove (`ParticipantForm`, `Participants`) | CP-2 (receipt-version gating) |
| Award item (`AwardItemSection`) | CP-2 |
| Campaign startup preference (`useSaveCampaignStartupPreference`) | returns outcomes already |
| Campaign setup (`CampaignSetupPage`) | waits for the authoritative bootstrap to list the campaign before navigating |

### 4.3 Compliant by design (navigate away, close, or intentionally need no reread)

Create-and-open and edit-and-return forms navigate to a destination that loads its own data, so there is no read-back to drop: `CreateWorldPage`, `EditWorldPage`, `CreateTimelinePage`, `EditTimelinePage`, `CreateTimelineBranchPage`, `ContentCreatePage`, `SessionFormPages` (schedule), `CalendarCreation`, `PartyForm` (create / edit), `RecordEventPage`, `CreateCharacterBuildPage` (`BuildForm`), `PrepareEncounterPage` (announces on the destination). `TravelSection` with `changed:false` records nothing and reads nothing.

### 4.4 Retained difference — "reload through the loading state" family (not changed)

The Phase 13 access, invitation, account, session-revocation and onboarding hooks (`useAccessOverview`, `useCampaignInvitations`, `usePlatformAccounts`, `useOwnSessions`, `useCampaignSession` boundaries, and the `Add/Change/Revoke…` mutation hooks such as `useAddCampaignMember`, `useAssignMembershipRole`, `useAddResourceGrant`, `useCreateAccessGroup`) do not keep a stale view after a write: their `retry()` increments a request version, the next render falls back to the **loading** state, and a failed read shows an explicit error page with **Try again**. No stale record is ever shown as current, so the DEF-001 harm ("done" while the screen is behind) cannot occur; the persistent status line ("Role added.") is true of the write. Changing this family would be a redesign of the 13E/13F pages, not a DEF-001 fix. **Reported as an assessed, unchanged family for Codex review**; a different decision (announce only after the reload) would be a separate change.

## 5. Intentional domain differences kept

- Row-version scopes (`StartControl`, `EndControl`, party row, session lifecycle) let the mutation's own status end with the record's version; callers that must outlive the version change (`TransitionControls`, `EntityLifecyclePanel`, `OrganizationMembers`, `WorldTimePicker`, `WorldTimesPage`) keep the unread write in component state and feed `useConfirmedRefresh` a synthetic `confirmed` status.
- Where the form that sent a write is replaced or removed by the recovered read (archived party row, started session, re-keyed portrayal, voided event) the **page** announces the write (`useAnnounceWhenRead`); the component announces only for its own **Load latest**.
- A denied/unavailable read-back is an authoritative answer (World Sharing after transfer; permission loss in the World workspace): the retained content is removed, nothing is held, and the write is still announced.
- Boundary-reload pages (§4.4), create/edit navigation (§4.3), and `Claim` lifecycle (page-level notice) keep their own shape.
- Wording is per domain ("party list", "campaign time", "world times"); no universal workspace framework was added.
