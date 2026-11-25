# World setup and canonical authoring

[HTTP catalog and common refusal/transaction rules](operations.md). The wire column names the JSON body and documented success response. A dash indicates no JSON request body. Check OpenAPI for path, header and query parameters. The gate column lists declared entry checks and known receipt stores. A handler can apply additional target and audience restrictions.

## Campaigns

[Handler and route-specific decisions](../../src/dnd_ai/api/campaigns.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns` | CreateCampaignRequest → 201 CreateCampaignResponse | human user id |
| `GET /campaigns/archived` | — → 200 object | human user id |
| `POST /campaigns/{campaign_id}/archive` | ArchiveCampaignRequest → 200 response | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/reactivate` | ReactivateCampaignRequest → 200 response | access.manage · campaign receipt |
| `GET /campaigns/{campaign_id}/settings` | — → 200 object | access.manage |
| `POST /campaigns/{campaign_id}/update` | UpdateCampaignRequest → 200 response | access.manage · campaign receipt |

## Dungeon authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/dungeon_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/dungeon-areas/{dungeon_area_id}` | — → 200 response | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/dungeon-areas/{dungeon_area_id}/update` | UpdateAreaRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons` | CreateDungeonRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/dungeons/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}` | — → 200 response | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/areas` | CreateAreaRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/connections` | AddConnectionRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/connections/{area_connection_id}/remove` | RemoveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/connections/{area_connection_id}/update` | UpdateConnectionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/features` | AddChildRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/features/{child_id}/remove` | RemoveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/features/{child_id}/update` | UpdateChildRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/hazards` | AddChildRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/hazards/{child_id}/remove` | RemoveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/hazards/{child_id}/update` | UpdateChildRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/interactables` | AddChildRequest → 201 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/interactables/{child_id}/remove` | RemoveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/interactables/{child_id}/update` | UpdateChildRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/dungeons/{dungeon_id}/update` | UpdateDungeonRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}/runtime` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}/state` | SetStateRequest → 200 response | canon.edit · campaign receipt |

## Entity lifecycle

[Handler and route-specific decisions](../../src/dnd_ai/api/entity_lifecycle.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/entities/{entity_id}/lifecycle` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/approve` | VersionOnlyRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/archive` | ReasonRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/delete-draft` | RequiredReasonRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/publish` | VersionOnlyRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/reject` | ReasonRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/replacement-candidates` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/restore` | RequiredReasonRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/return-to-draft` | ReasonRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/submit-for-review` | VersionOnlyRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/lifecycle/supersede` | SupersedeRequest → 200 response | canon.edit · campaign receipt |

## Item authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/item_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/items` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/authoring/items` | CreateItemRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/items/options` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/items/{item_instance_id}` | — → 200 response | canon.edit |
| `POST /campaigns/{campaign_id}/authoring/items/{item_instance_id}/update` | UpdateItemRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/attune` | AttuneRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/award` | AwardRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/consume` | AmountRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/damage` | AmountRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/destroy` | OperationBase → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/end-attunement` | OperationBase → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/equip` | OperationBase → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/repair` | AmountRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/items/{item_instance_id}/unequip` | OperationBase → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/parties/{party_id}/inventory` | — → 200 response | canon.edit |

## Item definition authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/item_definition_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/item-definitions` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/item-definitions` | DefinitionFields → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/item-definitions/options` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/item-definitions/{definition_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/item-definitions/{definition_id}/update` | UpdateDefinitionRequest → 200 response | canon.edit · campaign receipt |

## Knowledge authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/knowledge_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/knowledge` | CreateKnowledgeRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/knowledge/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/knowledge/subject-options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/knowledge/{knowledge_item_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/knowledge/{knowledge_item_id}/update` | UpdateKnowledgeRequest → 200 response | canon.edit · campaign receipt |

## Location authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/location_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/locations` | CreateLocationRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/locations/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/locations/parent-options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/locations/{location_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/locations/{location_id}/update` | UpdateLocationRequest → 200 response | canon.edit · campaign receipt |

## Npc authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/npc_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/npcs` | CreateNpcRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/npcs/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/npcs/{npc_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/npcs/{npc_id}/update` | UpdateNpcRequest → 200 response | canon.edit · campaign receipt |

## Npc portrayal

[Handler and route-specific decisions](../../src/dnd_ai/api/npc_portrayal.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/npc-runtime-options` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/authoring/npcs/{npc_id}/detail-level` | DetailLevelRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/npcs/{npc_id}/portrayal` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/npcs/{npc_id}/portrayal` | SavePortrayalRequest → 200 response | canon.edit · campaign receipt |

## Organization authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/organization_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/organizations` | CreateOrganizationRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/organizations/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/organizations/parent-options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/organizations/{organization_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/organizations/{organization_id}/update` | UpdateOrganizationRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/religions` | CreateReligionRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/religions/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/religions/reference-options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/religions/{religion_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/religions/{religion_id}/update` | UpdateReligionRequest → 200 response | canon.edit · campaign receipt |

## Player character authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/player_character_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/player-characters` | CreatePlayerCharacterRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/player-characters/options` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/authoring/player-characters/{player_character_id}` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/authoring/player-characters/{player_character_id}/update` | UpdatePlayerCharacterRequest → 200 response | canon.edit · campaign receipt |

## Quest authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/quest_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/authoring/quests` | CreateQuestRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/quests/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/quests/target-options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/quests/{quest_id}` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/dependencies` | DependencyRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/dependencies/{dependency_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/outcomes` | OutcomeRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/outcomes/{outcome_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/outcomes/{outcome_id}/rewards` | RewardRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/outcomes/{outcome_id}/update` | UpdateOutcomeRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/participants` | ParticipantRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/participants/{participant_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/rewards/{reward_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages` | StageRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/reorder` | ReorderRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/{stage_id}/objectives` | ObjectiveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/{stage_id}/objectives/{objective_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/{stage_id}/objectives/{objective_id}/update` | ObjectiveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/{stage_id}/remove` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/stages/{stage_id}/update` | StageRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/quests/{quest_id}/update` | UpdateQuestRequest → 200 response | canon.edit · campaign receipt |

## Relationship authoring

[Handler and route-specific decisions](../../src/dnd_ai/api/relationship_authoring.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/authoring/relationships` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/relationships` | CreateRelationshipRequest → 201 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/authoring/relationships/options` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/authoring/relationships/{relationship_id}` | — → 200 response | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/archive` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/change-office` | ChangeOfficeRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/end` | EndRelationshipRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/perspectives` | PerspectiveRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/restore` | VersionRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/authoring/relationships/{relationship_id}/update` | UpdateRelationshipRequest → 200 response | canon.edit · campaign receipt |

## Review queue

[Handler and route-specific decisions](../../src/dnd_ai/api/review_queue.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/entities/{entity_id}/revisions` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/entities/{entity_id}/revisions/compare` | — → 200 object | canon.edit, world.canon.read_private |
| `GET /campaigns/{campaign_id}/review-queue` | — → 200 object | canon.edit, world.canon.read_private |

## Rulesets

[Handler and route-specific decisions](../../src/dnd_ai/api/rulesets.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /rulesets` | — → 200 object | human user id |

## Sources

[Handler and route-specific decisions](../../src/dnd_ai/api/sources.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/entities/{entity_id}/provenance` | — → 200 response | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/sources/attach` | SourceLinkRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/entities/{entity_id}/sources/detach` | SourceLinkRequest → 200 response | canon.edit · campaign receipt |
| `GET /campaigns/{campaign_id}/sources` | — → 200 object | canon.edit, world.canon.read_private |
| `POST /campaigns/{campaign_id}/sources` | CreateSourceRequest → 201 response | canon.edit · campaign receipt |

## Timelines

[Handler and route-specific decisions](../../src/dnd_ai/api/timelines.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /worlds/{world_id}/timelines` | CreateTimelineRequest → 201 response | timeline.manage · actor receipt |
| `GET /worlds/{world_id}/timelines/{timeline_id}` | — → 200 object | world.view |
| `POST /worlds/{world_id}/timelines/{timeline_id}/archive` | TransitionTimelineRequest → 200 response | timeline.manage · actor receipt |
| `GET /worlds/{world_id}/timelines/{timeline_id}/branch-points` | — → 200 object | timeline.manage |
| `POST /worlds/{world_id}/timelines/{timeline_id}/branches` | CreateBranchRequest → 201 response | timeline.manage · actor receipt |
| `POST /worlds/{world_id}/timelines/{timeline_id}/restore` | TransitionTimelineRequest → 200 response | timeline.manage · actor receipt |
| `POST /worlds/{world_id}/timelines/{timeline_id}/update` | UpdateTimelineRequest → 200 response | timeline.manage · actor receipt |

## World canon

[Handler and route-specific decisions](../../src/dnd_ai/api/world_canon.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /worlds/{world_id}/canon` | — → 200 object | world.canon.read |

## World explorer

[Handler and route-specific decisions](../../src/dnd_ai/api/world_explorer.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/world/events/{event_id}` | — → 200 EventDetailResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/items/{item_instance_id}` | — → 200 ItemDetailResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/locations/{location_id}` | — → 200 LocationDetailResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/locations/{location_id}/children` | — → 200 LocationChildrenResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/organizations/{organization_id}` | — → 200 OrganizationDetailResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/relationships` | — → 200 RelationshipListResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/religions/{religion_id}` | — → 200 ReligionDetailResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/search` | — → 200 WorldEntitySearchResponse | campaign.view |
| `GET /campaigns/{campaign_id}/world/search/counts` | — → 200 WorldCategoryCountsResponse | campaign.view |

## World time

[Handler and route-specific decisions](../../src/dnd_ai/api/world_time.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/calendars` | — → 200 object | canon.edit |
| `GET /campaigns/{campaign_id}/world-times` | — → 200 object | canon.edit |
| `POST /campaigns/{campaign_id}/world-times` | CreateWorldTimeRequest → 201 response | canon.edit · campaign receipt |
| `GET /worlds/{world_id}/calendars` | — → 200 object | world.view |
| `POST /worlds/{world_id}/calendars` | CreateCalendarRequest → 201 response | world.manage · actor receipt |

## Worlds

[Handler and route-specific decisions](../../src/dnd_ai/api/worlds.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /worlds` | — → 200 object | human user id |
| `POST /worlds` | CreateWorldRequest → 201 response | human user id · actor receipt |
| `GET /worlds/{world_id}` | — → 200 object | world.view |
| `POST /worlds/{world_id}/archive` | TransitionWorldRequest → 200 response | world.manage · actor receipt |
| `POST /worlds/{world_id}/restore` | TransitionWorldRequest → 200 response | world.manage · actor receipt |
| `POST /worlds/{world_id}/update` | UpdateWorldRequest → 200 response | world.manage · actor receipt |
