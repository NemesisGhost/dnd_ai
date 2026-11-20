# Campaign play and integrations

[HTTP catalog and common refusal/transaction rules](operations.md). The wire column names the JSON body and documented success response. A dash indicates no JSON request body. Check OpenAPI for path, header and query parameters. The gate column lists declared entry checks and known receipt stores. A handler can apply additional target and audience restrictions.

## Ai npc

[Handler and route-specific decisions](../../src/dnd_ai/api/ai_npc.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/ai/npc-conversation` | NpcConversationTurnRequest → 200 NpcConversationTurnResponse | character.interact |
| `POST /campaigns/{campaign_id}/ai/proposed-changes/{ai_proposed_change_id}/review` | ReviewProposedChangeRequest → 200 ReviewProposedChangeResponse | canon.edit |

## Ai synthesis

[Handler and route-specific decisions](../../src/dnd_ai/api/ai_synthesis.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/ai/synthesis` | CampaignSynthesisRequest → 200 CampaignSynthesisResponse | campaign.view |

## App

[Handler and route-specific decisions](../../src/dnd_ai/api/app.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /healthz` | — → 200 object | public probe |
| `GET /readyz` | — → 200 | public probe |

## Campaign clock

[Handler and route-specific decisions](../../src/dnd_ai/api/campaign_clock.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/clock` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/clock/advance` | AdvanceClockRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/clock/cause-choices` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/clock/correct` | CorrectClockRequest → 200 response | canon.edit · campaign receipt |

## Character builds

[Handler and route-specific decisions](../../src/dnd_ai/api/character_builds.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/character-build-options` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/characters/{character_id}/builds` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/authoring/characters/{character_id}/builds` | CreateBuildRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/characters/{character_id}/builds/{build_id}/activate` | ActivateBuildRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/characters/{character_id}/state/initialize` | InitializeStateRequest → 201 response | canon.edit · campaign receipt |

## Character state

[Handler and route-specific decisions](../../src/dnd_ai/api/character_state.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/characters/{character_id}/conditions` | ApplyCharacterConditionRequest → 200 ApplyCharacterConditionResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/conditions/{condition_id}/remove` | RemoveCharacterConditionRequest → 200 RemoveCharacterConditionResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/hit-points` | AdjustHitPointsRequest → 200 AdjustHitPointsResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/resources` | AdjustCharacterResourceRequest → 200 AdjustCharacterResourceResponse | canon.edit · campaign receipt |

## Characters

[Handler and route-specific decisions](../../src/dnd_ai/api/characters.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/characters/{character_id}` | — → 200 CharacterResponse or PublicCharacterResponse | campaign.view |
| `GET /campaigns/{campaign_id}/characters/{character_id}/inventory` | — → 200 InventoryItemResponse[] or RestrictedInventoryItemResponse[] | campaign.view |
| `GET /campaigns/{campaign_id}/characters/{character_id}/parties` | — → 200 CharacterPartiesResponse | campaign.view |
| `GET /campaigns/{campaign_id}/characters/{character_id}/relationships` | — → 200 CharacterRelationshipsResponse | campaign.view |
| `GET /campaigns/{campaign_id}/characters/{character_id}/sheet` | — → 200 CharacterSheetResponse | campaign.view |

## Dungeon

[Handler and route-specific decisions](../../src/dnd_ai/api/dungeon.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}` | — → 200 DungeonAreaResponse | campaign.view |

## Encounter preparation

[Handler and route-specific decisions](../../src/dnd_ai/api/encounter_preparation.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/encounters` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/encounters/options` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/encounters/{encounter_id}` | — → 200 response | canon.edit |
| `POST /campaigns/{campaign_id}/encounters/prepare` | PrepareRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/abort` | OperationRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/participants` | dnd_ai__api__encounter_preparation__AddParticipantRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/participants/{participant_id}/remove` | — → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/participants/{participant_id}/update` | UpdateParticipantRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/start` | OperationRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/update` | UpdateEncounterRequest → 200 response | canon.edit · campaign receipt |

## Encounters

[Handler and route-specific decisions](../../src/dnd_ai/api/encounters.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/encounters` | StartEncounterRequest → 201 EncounterResponse | canon.edit |
| `GET /campaigns/{campaign_id}/encounters/{encounter_id}` | — → 200 EncounterDetailResponse | campaign.view |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/end` | EndEncounterRequest → 200 EndEncounterResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/encounters/{encounter_id}/turns` | ResolveCombatTurnRequest → 201 ResolveCombatTurnResponse | canon.edit · campaign receipt |

## Event corrections

[Handler and route-specific decisions](../../src/dnd_ai/api/event_corrections.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/events/{event_id}` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/events/{event_id}/correct` | CorrectEventRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/events/{event_id}/correction-preview` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/events/{event_id}/void` | VoidEventRequest → 200 response | canon.edit · campaign receipt |

## Events

[Handler and route-specific decisions](../../src/dnd_ai/api/events.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/events` | RecordEventRequest → 201 RecordEventResponse | canon.edit · campaign receipt |

## Foundry pairing

[Handler and route-specific decisions](../../src/dnd_ai/api/foundry_pairing.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `DELETE /campaigns/{campaign_id}/foundry/connections/{foundry_connection_id}` | — → 204 | access.manage |
| `GET /campaigns/{campaign_id}/foundry/devices` | — → 200 FoundryDeviceResponse[] | access.manage |
| `DELETE /campaigns/{campaign_id}/foundry/devices/{foundry_device_id}` | — → 204 | access.manage |
| `POST /campaigns/{campaign_id}/foundry/pairing-codes` | CreatePairingCodeRequest → 201 CreatePairingCodeResponse | campaign.view |
| `GET /foundry/devices` | — → 200 FoundryDeviceResponse[] | human user id |
| `DELETE /foundry/devices/{foundry_device_id}` | — → 204 | human user id |
| `POST /foundry/devices/{foundry_device_id}/rotate` | RotateFoundryDeviceRequest → 200 RotateFoundryDeviceResponse | human user id |
| `POST /foundry/pair` | ConsumeFoundryPairingCodeRequest → 201 ConsumeFoundryPairingCodeResponse | valid single-use pairing code, rate limited |
| `POST /foundry/token` | — → 200 FoundryTokenResponse | FoundryDevice credential, rate limited |

## Integration

[Handler and route-specific decisions](../../src/dnd_ai/api/integration.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/integration/external-systems` | RegisterExternalSystemRequest → 201 RegisterExternalSystemResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/integration/external-systems/{external_system_id}/foundry-identities` | LinkFoundryIdentityRequest → 200 LinkFoundryIdentityResponse | access.manage |
| `POST /campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers` | MapExternalIdentifierRequest → 200 MapExternalIdentifierResponse | canon.edit |
| `GET /campaigns/{campaign_id}/integration/external-systems/{external_system_id}/sync-state` | — → 200 SyncStateResponse | campaign.view |
| `POST /campaigns/{campaign_id}/integration/foundry/combat-sync` | ApplyFoundryCombatSyncRequest → 201 ApplyFoundryCombatSyncResponse | canon.edit |

## Interactions

[Handler and route-specific decisions](../../src/dnd_ai/api/interactions.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/checks/{check_request_id}/resolve` | ResolveCheckRequest → 201 ResolveCheckResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/interactions` | PerformInteractionRequest → 201 PerformInteractionResponse | canon.edit · campaign receipt |

## Items

[Handler and route-specific decisions](../../src/dnd_ai/api/items.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/identify` | IdentifyItemRequest → 200 IdentifyItemResponse | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/transfer` | TransferItemPossessionRequest → 200 TransferItemPossessionResponse | canon.edit · campaign receipt |

## Knowledge

[Handler and route-specific decisions](../../src/dnd_ai/api/knowledge.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/knowledge` | — → 200 KnowledgeListResponse | campaign.view |
| `GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}` | — → 200 KnowledgeResponse | campaign.view |

## Knowledge runtime

[Handler and route-specific decisions](../../src/dnd_ai/api/knowledge_runtime.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/knowledge/knowers/{entity_knowledge_id}/belief` | BeliefRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}/audience` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/knowledge/{knowledge_item_id}/learn` | LearnRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/knowledge/{knowledge_item_id}/make-public` | PublicRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/knowledge/{knowledge_item_id}/reveal-to-party` | RevealRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/knowledge/{knowledge_item_id}/transfer` | TransferRequest → 200 response | canon.edit · campaign receipt |

## Movement

[Handler and route-specific decisions](../../src/dnd_ai/api/movement.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/characters/{character_id}/location` | EnterLocationRequest → 200 EnterLocationResponse | canon.edit · campaign receipt |

## Organization members

[Handler and route-specific decisions](../../src/dnd_ai/api/organization_members.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/organizations/{organization_id}/members` | — → 200 object | campaign.view |

## Parties

[Handler and route-specific decisions](../../src/dnd_ai/api/parties.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/parties` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/parties` | PartyFields → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/parties/{party_id}` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/parties/{party_id}/archive` | ArchivePartyRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/parties/{party_id}/members` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/parties/{party_id}/members` | AddMemberRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/parties/{party_id}/members/{party_membership_id}/end` | EndMembershipRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/parties/{party_id}/restore` | RestorePartyRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/parties/{party_id}/roster` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/parties/{party_id}/update` | UpdatePartyRequest → 200 response | canon.edit · campaign receipt |

## Quest runtime

[Handler and route-specific decisions](../../src/dnd_ai/api/quest_runtime.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/quests/objectives/{quest_objective_id}/status` | ObjectiveStatusRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/abandon` | QuestActionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/activate` | QuestActionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/complete` | QuestActionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/fail` | QuestActionRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/quests/{quest_id}/progress` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/resume` | QuestActionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/quests/{quest_id}/suspend` | QuestActionRequest → 200 response | canon.edit · campaign receipt |

## Quests

[Handler and route-specific decisions](../../src/dnd_ai/api/quests.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/quests` | — → 200 QuestListItemResponse[] | campaign.view |
| `POST /campaigns/{campaign_id}/quests/objectives/{quest_objective_id}/advance` | AdvanceObjectiveRequest → 200 AdvanceObjectiveResponse | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/quests/{quest_id}` | — → 200 QuestResponse | campaign.view |

## Reference corpus

[Handler and route-specific decisions](../../src/dnd_ai/api/reference_corpus.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `DELETE /campaigns/{campaign_id}/reference-corpus/grants/{reference_source_campaign_id}` | — → 204 | rules_source.manage |
| `POST /campaigns/{campaign_id}/reference-corpus/query` | RetrieveCitedPassagesRequest → 200 RetrieveCitedPassagesResponse | campaign.view |
| `POST /campaigns/{campaign_id}/reference-corpus/sources` | RegisterSourceDocumentRequest → 201 RegisterSourceDocumentResponse | rules_source.manage |
| `DELETE /campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}` | — → 204 | rules_source.manage |
| `POST /campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}/grant` | GrantSourceToCampaignRequest → 201 GrantSourceToCampaignResponse | rules_source.manage |
| `POST /campaigns/{campaign_id}/reference-corpus/sources/{source_document_id}/passages` | IngestReferencePassagesRequest → 201 IngestReferencePassagesResponse | rules_source.manage |

## Relationships

[Handler and route-specific decisions](../../src/dnd_ai/api/relationships.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/organizations/{organization_id}` | — → 200 OrganizationResponse | campaign.view |
| `POST /campaigns/{campaign_id}/organizations/{organization_id}/status` | UpdateOrganizationStatusRequest → 200 UpdateOrganizationStatusResponse | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/relationships/{relationship_id}` | — → 200 RelationshipResponse | campaign.view |
| `POST /campaigns/{campaign_id}/relationships/{relationship_id}/evolve` | EvolveRelationshipReactionRequest → 200 EvolveRelationshipReactionResponse | canon.edit · campaign receipt |

## Session authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/session_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/sessions` | SessionFields → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/archive` | ArchiveSessionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/restore` | RestoreSessionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/update` | UpdateSessionRequest → 200 response | canon.edit · campaign receipt |

## Session play

[Handler and route-specific decisions](../../src/dnd_ai/api/session_play.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/sessions/{session_id}/end` | EndSessionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/log` | LogEntryRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/participants` | dnd_ai__api__session_play__AddParticipantRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/participants/{session_participant_id}/remove` | RemoveParticipantRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/start` | StartSessionRequest → 200 response | canon.edit · campaign receipt |

## Sessions

[Handler and route-specific decisions](../../src/dnd_ai/api/sessions.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/sessions` | — → 200 SessionListItemResponse[] | campaign.view |
| `GET /campaigns/{campaign_id}/sessions/{session_id}` | — → 200 SessionDetailResponse | campaign.view |

## Summary

[Handler and route-specific decisions](../../src/dnd_ai/api/summary.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/summary` | — → 200 CampaignSummaryResponse | campaign.view |

## Travel

[Handler and route-specific decisions](../../src/dnd_ai/api/travel.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/routes` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/sessions/{session_id}/travel` | TravelRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/travel` | TravelRequest → 200 response | canon.edit · campaign receipt |
