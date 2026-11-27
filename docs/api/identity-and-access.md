# Identity, permissions and profiles

[HTTP catalog and common refusal/transaction rules](operations.md). The wire column names the JSON body and documented success response. A dash indicates no JSON request body. Check OpenAPI for path, header and query parameters. The gate column lists declared entry checks and known receipt stores. A handler can apply additional target and audience restrictions.

## Control assignments

[Handler and route-specific decisions](../../src/dnd_ai/api/control_assignments.py) · [Contract](ACCESS_CONTROL.md#3z-assign-replace-and-revoke-control-p15-c11-s02-t01)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/characters/{character_id}/control-assignments` | — → 200 CharacterControlResponse | campaign.view · assign-control authority (built-in owner or gm), judged before any character lookup · no lock |
| `POST /campaigns/{campaign_id}/characters/{character_id}/control-assignments` | AssignRequest → 201 AssignmentCreatedResponse | campaign.view · assign-control authority · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/control-assignments/replace-primary` | ReplaceRequest → 201 PrimaryReplacedResponse | campaign.view · assign-control authority · campaign receipt |
| `POST /campaigns/{campaign_id}/control-assignments/{control_assignment_id}/revoke` | RevokeRequest (optional) → 200 AssignmentRevokedResponse | campaign.view · assign-control authority · campaign receipt |

## Access grants

[Handler and route-specific decisions](../../src/dnd_ai/api/access_grants.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/change` | ChangeCharacterRelationshipRequest → 201 dnd_ai__api__access_grants__CharacterRelationshipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/revoke` | — → 200 dnd_ai__api__access_grants__CharacterRelationshipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/character-relationships` | GrantCharacterRelationshipRequest → 201 dnd_ai__api__access_grants__CharacterRelationshipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/resource-grants` | CreateResourceGrantRequest → 201 ResourceGrantResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/resource-grants/{resource_grant_id}/revoke` | — → 200 ResourceGrantResponse | access.manage · campaign receipt |

## Access groups

[Handler and route-specific decisions](../../src/dnd_ai/api/access_groups.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/access-group-memberships/{access_group_membership_id}/remove` | — → 200 AccessGroupMembershipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/access-groups` | CreateAccessGroupRequest → 201 AccessGroupResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/deactivate` | — → 200 AccessGroupResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/members` | AddAccessGroupMemberRequest → 201 AccessGroupMembershipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/reactivate` | — → 200 AccessGroupResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/update` | UpdateAccessGroupRequest → 200 AccessGroupResponse | access.manage · campaign receipt |

## Access overview

[Handler and route-specific decisions](../../src/dnd_ai/api/access_overview.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/access-overview` | — → 200 CampaignAccessOverviewResponse | access.manage |
| `GET /campaigns/{campaign_id}/eligible-accounts` | — → 200 EligibleAccountLookupResponse | access.manage |
| `GET /campaigns/{campaign_id}/members/{campaign_membership_id}/effective-access` | — → 200 MemberEffectiveAccessResponse | access.manage |

## Audit history

[Handler and route-specific decisions](../../src/dnd_ai/api/audit_history.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/audit-history` | — → 200 AuditHistoryListResponse | access.manage |
| `GET /campaigns/{campaign_id}/audit-history/actors` | — → 200 AuditActorListResponse | access.manage |

## Campaign invitations

[Handler and route-specific decisions](../../src/dnd_ai/api/campaign_invitations.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaign-invitations/accept` | AcceptCampaignInvitationRequest → 200 AcceptCampaignInvitationResponse | human user id |
| `GET /campaigns/{campaign_id}/invitations` | — → 200 PendingCampaignInvitationListResponse | access.manage |
| `POST /campaigns/{campaign_id}/invitations` | CreateCampaignInvitationRequest → 201 CreateCampaignInvitationResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/invitations/{campaign_invitation_id}/revoke` | — → 200 RevokeCampaignInvitationResponse | access.manage · campaign receipt |

## Character public profile

[Handler and route-specific decisions](../../src/dnd_ai/api/character_public_profile.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/characters/{character_id}/public-profile` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft` | SaveCharacterPublicProfileDraftRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft/copy-legacy` | CopyLegacyTextRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft/copy-player-profile` | CopyPlayerProfileFieldRequest → 200 response | canon.edit · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/releases` | ReleaseCharacterPublicProfileRequest → 200 response | campaign.view · campaign receipt |
| `GET /campaigns/{campaign_id}/characters/{character_id}/public-profile/releases/{version_number}` | — → 200 object | campaign.view |

## Character reveal

[Handler and route-specific decisions](../../src/dnd_ai/api/character_reveal.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/reveal-delegations` | — → 200 RevealDelegationStateResponse | access.manage |
| `POST /campaigns/{campaign_id}/reveal-delegations` | GrantCharacterRevealDelegationRequest → 200 GrantCharacterRevealDelegationResponse | access.manage |
| `POST /campaigns/{campaign_id}/reveal-delegations/{grantee_campaign_membership_id}/revoke` | RevokeCharacterRevealDelegationRequest → 200 RevokeCharacterRevealDelegationResponse | access.manage |

## Character revelations

[Handler and route-specific decisions](../../src/dnd_ai/api/character_revelations.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/characters/{character_id}/revelations` | — → 200 object | campaign.view |
| `POST /campaigns/{campaign_id}/characters/{character_id}/revelations` | CreateCharacterRevelationRequest → 200 response | campaign.view · campaign receipt |
| `POST /campaigns/{campaign_id}/characters/{character_id}/revelations/{character_revelation_id}/revoke` | RevokeCharacterRevelationRequest → 200 response | campaign.view · campaign receipt |

## Invitation onboarding

[Handler and route-specific decisions](../../src/dnd_ai/api/invitation_onboarding.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaign-invitations/onboarding/cancel` | — → 204 | allowed origin |
| `POST /campaign-invitations/onboarding/complete` | — → 200 CompleteOnboardingResponse | human user id |
| `POST /campaign-invitations/onboarding/register` | RegisterInvitedAccountRequest → 201 RegisterInvitedAccountResponse | allowed origin |
| `POST /campaign-invitations/onboarding/start` | BeginOnboardingRequest → 201 BeginOnboardingResponse | allowed origin |
| `GET /campaign-invitations/onboarding/status` | — → 200 OnboardingStatusResponse | valid onboarding cookie |

## Local auth

[Handler and route-specific decisions](../../src/dnd_ai/api/local_auth.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /admin/accounts` | — → 200 PlatformAccountListResponse | human user id |
| `POST /admin/accounts` | CreateAccountRequest → 201 CreateAccountResponse | human user id |
| `POST /admin/accounts/{target_user_id}/disable` | — → 200 AccountLifecycleResponse | human user id |
| `POST /admin/accounts/{target_user_id}/password-reset` | IssuePasswordResetRequest → 201 IssuePasswordResetResponse | human user id |
| `POST /admin/accounts/{target_user_id}/reactivate` | — → 200 AccountLifecycleResponse | human user id |
| `POST /admin/accounts/{target_user_id}/revoke-sessions` | — → 200 AdminRevokeAllSessionsResponse | human user id |
| `POST /admin/accounts/{target_user_id}/system-roles` | SystemRoleAssignmentRequest → 200 SystemRoleChangeResponse | human user id |
| `POST /admin/accounts/{target_user_id}/system-roles/{system_role_code}/revoke` | — → 200 SystemRoleChangeResponse | human user id |
| `POST /auth/activate` | ActivateAccountRequest → 200 ActivateAccountResponse | allowed origin |
| `POST /auth/activation-status` | ActivationStatusRequest → 200 ActivationStatusResponse | allowed origin |
| `POST /auth/change-password` | ChangePasswordRequest → 204 | human user id |
| `POST /auth/login` | LoginRequest → 200 LoginResponse | allowed origin |
| `POST /auth/logout` | — → 204 | human user id |
| `POST /auth/password-reset` | ResetPasswordRequest → 200 ResetPasswordResponse | allowed origin |
| `POST /auth/password-reset-status` | PasswordResetStatusRequest → 200 PasswordResetStatusResponse | allowed origin |
| `GET /auth/session` | — → 200 SessionBootstrapResponse | authenticated human (local session or compatible bearer) |
| `GET /auth/sessions` | — → 200 BrowserSessionSummaryResponse[] | human user id |
| `DELETE /auth/sessions/{browser_session_id}` | — → 204 | human user id |

## Memberships

[Handler and route-specific decisions](../../src/dnd_ai/api/memberships.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `POST /campaigns/{campaign_id}/memberships` | CreateCampaignMembershipRequest → 201 CampaignMembershipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change` | ChangeMembershipRoleRequest → 201 MembershipRoleResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke` | — → 200 MembershipRoleResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/end` | — → 200 EndCampaignMembershipResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/roles` | AssignMembershipRoleRequest → 201 MembershipRoleResponse | access.manage · campaign receipt |
| `POST /campaigns/{campaign_id}/ownership-transfer` | TransferCampaignOwnershipRequest → 200 TransferCampaignOwnershipResponse | access.manage |

## Player profiles

[Handler and route-specific decisions](../../src/dnd_ai/api/player_profiles.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/characters/{character_id}/player-profile` | — → 200 object | campaign.view |
| `GET /campaigns/{campaign_id}/characters/{character_id}/player-profile/versions/{profile_row_version}` | — → 200 object | campaign.view |

## Preview

[Handler and route-specific decisions](../../src/dnd_ai/api/preview.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge` | — → 200 KnowledgeListResponse | access.manage |
| `GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/perspectives` | — → 200 PreviewPerspectivesResponse | access.manage |
| `GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/{knowledge_item_id}` | — → 200 KnowledgeResponse | access.manage |
| `GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/quests/{quest_id}` | — → 200 QuestResponse | access.manage |

## User preferences

[Handler and route-specific decisions](../../src/dnd_ai/api/user_preferences.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `PUT /auth/preferences/campaign-startup` | CampaignStartupPreferenceRequest → 204 | human user id |
| `PUT /auth/preferences/last-visited-campaign` | LastVisitedCampaignRequest → 204 | human user id |

## World sharing

[Handler and route-specific decisions](../../src/dnd_ai/api/world_sharing.py)

| Method and API path | Request → success | Entry checks / receipt |
|---|---|---|
| `GET /worlds/{world_id}/access` | — → 200 object | world.share |
| `POST /worlds/{world_id}/ownership-transfer` | TransferOwnershipRequest → 200 response | world.transfer · actor receipt |
| `POST /worlds/{world_id}/roles` | AssignWorldRoleRequest → 200 response | world.share · actor receipt |
| `POST /worlds/{world_id}/roles/{world_membership_id}/end` | — → 200 response | world.share · actor receipt |
| `POST /worlds/{world_id}/use-grants` | GrantWorldUseRequest → 200 response | world.share · actor receipt |
| `POST /worlds/{world_id}/use-grants/{world_use_grant_id}/revoke` | — → 200 response | world.share · actor receipt |
