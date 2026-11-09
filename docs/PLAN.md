# Documentation routing for legacy PLAN references

The implementation encyclopedia formerly at this path has been retired. This file is a
compatibility index for existing source citations, not a second plan. New work starts at
[the documentation index](README.md), [current status](PROJECT_STATUS.md), and the
[authoring-first roadmap](PLANv2.md). The active Phase 15/P03-A acceptance gates remain.

The original text is available at [commit 53416d5](https://github.com/NemesisGhost/dnd_ai/blob/53416d5/docs/PLAN.md).
Original phase numbering in source comments may predate later renumbering; use the topic
name as well as its number. Remove this pointer only after those citations are migrated.

## Current authority by topic

| Topic | Reference |
|---|---|
| Domain/schema/commands | DOMAIN_MODEL, architecture/DATABASE_MODEL, ENTITY_LIFECYCLE |
| Service and transaction boundaries | architecture/SYSTEM_ARCHITECTURE |
| Identity and access | api/ACCESS_CONTROL |
| Verification, phase exit and testing | DEVELOPMENT §6, §10–11 |
| Phase 15 original checkpoint sequence | PHASE15_VERIFICATION |
| Dungeon vertical slice | architecture/DUNGEON_FLOW |
| Deployment and recovery | LOCAL_DEPLOYMENT, operations/DATABASE_RECOVERY |
| Optional AWS | INFRASTRUCTURE |

## Legacy section anchors

Anchors are grouped by maintained destination. Their original numbered text remains in
the historical document linked above; these entries do not revive superseded policies.

<a id="table-of-contents"></a>
<a id="1-purpose"></a>
<a id="2-architectural-decisions"></a>
<a id="21-postgresql-is-the-source-of-truth"></a>
<a id="22-use-class-table-inheritance"></a>
<a id="23-worlds-timelines-campaigns-and-sessions-are-separate-concepts"></a>
<a id="24-definition-and-state-are-separate"></a>
<a id="25-event-assisted-state-model"></a>
<a id="26-structured-data-is-authoritative-generated-text-is-derived"></a>
<a id="27-reference-corpus-ingestion-and-campaign-import-are-separate-systems"></a>
<a id="28-browser-authentication-is-local-and-uses-a-server-side-session-boundary"></a>
<a id="3-postgresql-schema-organization"></a>
<a id="31-schema-responsibilities"></a>
<a id="4-foundation-implementation"></a>
<a id="41-postgresql-extensions"></a>
<a id="42-shared-domains"></a>
<a id="43-foundation-tables"></a>
<a id="44-canon-lifecycle"></a>
<a id="45-provenance"></a>
<a id="5-world-timeline-campaign-party-and-session-implementation"></a>
<a id="51-worlds"></a>
<a id="52-timelines"></a>
<a id="53-campaigns"></a>
<a id="54-parties"></a>
<a id="55-sessions"></a>
<a id="6-ruleset-implementation"></a>
<a id="61-ruleset-separation"></a>
<a id="62-homebrew-support"></a>
<a id="63-derived-calculations"></a>
<a id="7-shared-character-implementation"></a>
<a id="71-character-hierarchy"></a>
<a id="72-shared-character-data"></a>
<a id="73-timeline-state"></a>
<a id="74-character-control"></a>
<a id="8-npc-world-management-implementation"></a>
<a id="81-simulation-levels"></a>
<a id="82-portrayal-profiles"></a>
<a id="83-goals"></a>
<a id="9-geography-and-dungeon-implementation"></a>
<a id="91-location-hierarchy"></a>
<a id="92-dungeon-structures"></a>
<a id="93-dungeon-timeline-state"></a>
<a id="94-discovery-versus-existence"></a>
<a id="10-universal-relationship-implementation"></a>
<a id="101-objective-versus-subjective-data"></a>
<a id="102-specialized-relationship-subtypes"></a>
<a id="11-organization-government-business-and-religion-implementation"></a>
<a id="111-organization-hierarchy"></a>
<a id="112-organizations"></a>
<a id="113-religion-distinction"></a>
<a id="12-items-inventory-ownership-and-treasure-implementation"></a>
<a id="121-definitions-and-instances"></a>
<a id="122-item-state"></a>
<a id="13-event-implementation"></a>
<a id="131-events-as-first-class-entities"></a>
<a id="132-event-effects"></a>
<a id="133-event-granularity"></a>
<a id="14-quest-and-narrative-implementation"></a>
<a id="141-quest-definitions-and-progress"></a>
<a id="142-event-driven-advancement"></a>
<a id="15-knowledge-belief-rumor-and-discovery-implementation"></a>
<a id="151-knowledge-types"></a>
<a id="152-truth-and-belief"></a>
<a id="153-discovery-model"></a>
<a id="154-information-propagation"></a>
<a id="16-interaction-and-resolution-implementation"></a>
<a id="161-resolution-flow"></a>
<a id="162-external-integration"></a>
<a id="17-encounter-and-combat-implementation"></a>
<a id="18-ai-agent-implementation"></a>
<a id="181-agent-roles"></a>
<a id="182-controlled-mutation"></a>
<a id="183-rulesreference-corpus-ingestion-and-retrieval"></a>
<a id="19-effective-state-resolution"></a>
<a id="191-resolution-order"></a>
<a id="192-typed-state-first"></a>
<a id="193-query-services"></a>
<a id="20-transaction-and-command-model"></a>
<a id="21-audit-and-validation-implementation"></a>
<a id="22-worldcampaign-data-import-implementation"></a>
<a id="progress-at-a-glance"></a>
<a id="deliverables"></a>
<a id="exit-criteria"></a>
<a id="141-domain-command-foundation"></a>
<a id="142-initial-command-catalog"></a>
<a id="143-campaign-setup-workflow"></a>
<a id="144-reusable-portal-authoring-patterns"></a>
<a id="145-development-data-conversion"></a>
<a id="15a-world-structure-and-places"></a>
<a id="15b-organizations-factions-religions-governments-and-businesses"></a>
<a id="15c-characters-and-npcs"></a>
<a id="15d-quests-and-narrative-planning"></a>
<a id="15e-sessions-events-knowledge-and-corrections"></a>
<a id="15f-items-inventory-treasure-and-encounters"></a>
<a id="15g-canon-review-and-history"></a>
<a id="16a-character-owned-authoring"></a>
<a id="16b-notes-bookmarks-and-theories"></a>
<a id="16c-player-private-collaboration"></a>
<a id="16d-player-session-contributions"></a>
<a id="16e-player-campaign-experience"></a>
<a id="171-browser-acceptance"></a>
<a id="172-accessibility-and-responsive-acceptance"></a>
<a id="173-production-packaging"></a>
<a id="174-standalone-completion-gate"></a>
<a id="18a-source-intake-and-staging"></a>
<a id="18b-session-note-intelligence"></a>
<a id="18c-reviewable-change-sets"></a>
<a id="18d-promotion-through-authoring-commands"></a>
<a id="18e-broader-worldcampaign-import"></a>
<a id="186-exit-criteria"></a>
<a id="191-rules-content-and-policy"></a>
<a id="192-character-advancement"></a>
<a id="193-creature-model-decision-and-implementation"></a>
<a id="194-encounter-analysis"></a>
<a id="202-grounded-user-surfaces"></a>
<a id="203-structured-live-scenes"></a>
<a id="21a-foundryvtt"></a>
<a id="21b-other-vtt-and-importexport-adapters"></a>
<a id="21c-bots-messaging-mcp-and-transcription-providers"></a>
<a id="16-authoring-ownership-and-approval-matrix"></a>
<a id="17-cross-cutting-delivery-requirements"></a>
<a id="171-security-and-authorization"></a>
<a id="172-data-integrity-and-history"></a>
<a id="173-idempotency-and-concurrency"></a>
<a id="174-audit-and-provenance"></a>
<a id="175-ux-and-accessibility"></a>
<a id="176-testing-and-evidence"></a>
<a id="later-phases-demonstrated-need-expansion"></a>

Current topic: [README.md](README.md).

<a id="29-phase-13-ui-authorship"></a>
<a id="phase-0-documentation-and-decision-records"></a>
<a id="phase-1-database-bootstrap"></a>
<a id="phase-2-core-world-platform"></a>
<a id="phase-3-timelines-and-campaigns"></a>
<a id="phase-4-rules-and-shared-characters"></a>
<a id="phase-5-locations-and-dungeon-play"></a>
<a id="phase-6-events-and-interactions"></a>
<a id="phase-7-quests-and-knowledge"></a>
<a id="phase-8-relationships-and-organizations"></a>
<a id="phase-9-items-inventory-encounters-and-foundry-integration-contracts"></a>
<a id="phase-10-core-api-and-playable-vertical-slice"></a>
<a id="phase-11-foundry-mvp"></a>
<a id="phase-12-narrow-ainpc-mvp"></a>
<a id="phase-13-web-portal-mvp-and-same-origin-packaging"></a>
<a id="phase-14-shared-authoring-kernel-and-campaign-setup"></a>
<a id="146-phase-14-exit-criteria"></a>
<a id="phase-16-player-authoring-contribution-and-collaboration"></a>
<a id="166-phase-16-exit-scenario"></a>
<a id="167-phase-16-exit-criteria"></a>
<a id="phase-17-standalone-product-acceptance-and-self-hosted-packaging"></a>
<a id="phase-18-session-intelligence-and-controlled-import"></a>
<a id="phase-19-rules-aware-character-creature-and-encounter-expansion"></a>
<a id="phase-20-grounded-assistance-and-structured-npc-scenes"></a>
<a id="201-close-the-existing-phase-12-foundation"></a>
<a id="phase-21-integrations-and-adapters"></a>
<a id="phase-22-hosted-offering-and-demonstrated-need-expansion"></a>
<a id="314-networking-decisions-for-phase-10"></a>

Current topic: [PLANv2.md](PLANv2.md).

<a id="23-identity-authorization-and-web-portal-implementation"></a>
<a id="231-identity-and-campaign-membership"></a>
<a id="232-many-to-many-user-and-resource-relationships"></a>
<a id="233-authorization-and-non-disclosure"></a>
<a id="234-browser-session-boundary"></a>
<a id="235-foundry-hybrid-pairing-and-device-authentication"></a>
<a id="236-web-portal-experience"></a>
<a id="237-audience-aware-summaries-questions-and-feature-boundaries"></a>

Current topic: [api/ACCESS_CONTROL.md](api/ACCESS_CONTROL.md).

<a id="24-delivery-phases"></a>
<a id="240-verification-policy"></a>
<a id="241-phase-exit-review"></a>
<a id="25-vertical-slice-acceptance-scenario"></a>
<a id="26-testing-strategy"></a>
<a id="261-database-tests"></a>
<a id="262-application-service-and-api-tests"></a>
<a id="263-scenario-tests"></a>
<a id="264-property-based-tests"></a>
<a id="265-performance-tests"></a>
<a id="266-proportional-test-infrastructure-policy"></a>
<a id="267-portal-testing"></a>

Current topic: [DEVELOPMENT.md#11-delivery-verification-and-phase-exit-review](DEVELOPMENT.md#11-delivery-verification-and-phase-exit-review).

<a id="phase-15-game-master-authoring-and-campaign-operations"></a>
<a id="158-gm-authoring-exit-scenario"></a>
<a id="159-phase-15-exit-criteria"></a>

Current topic: [PHASE15_VERIFICATION.md#original-authoring-checkpoint-sequence-and-exit-obligation](PHASE15_VERIFICATION.md#original-authoring-checkpoint-sequence-and-exit-obligation).

<a id="27-operational-strategy"></a>
<a id="271-migrations"></a>
<a id="272-environments"></a>
<a id="273-backups"></a>
<a id="274-observability"></a>
<a id="32-local-production-deployment-plan"></a>

Current topic: [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md).

<a id="28-deferred-decisions"></a>
<a id="29-definition-of-implementation-success"></a>

Current topic: [BACKLOG.md](BACKLOG.md).

<a id="30-aws-terraform-deployment-plan-for-postgresql"></a>
<a id="301-scope-and-current-state"></a>
<a id="302-remote-terraform-state"></a>
<a id="303-environments-dev-staging-prod"></a>
<a id="304-provisioning-order"></a>
<a id="305-database-role-schema-and-extension-bootstrap"></a>
<a id="306-migration-execution-mechanism"></a>
<a id="307-deployment-runbook"></a>
<a id="308-open-items"></a>
<a id="309-shared-dev-verification-mechanism-historical-superseded-as-cis-mechanism-by-adr-0012"></a>
<a id="31-aws-deployment-plan-for-application-services"></a>
<a id="311-scope-and-initial-target"></a>
<a id="312-compute-principles"></a>
<a id="313-packaging-and-release"></a>
<a id="315-identity-portal-hosting-and-secrets"></a>
<a id="316-deployment-flow"></a>
<a id="317-observability"></a>
<a id="318-per-phase-deployment-expectations"></a>
<a id="319-open-items"></a>

Current topic: [INFRASTRUCTURE.md](INFRASTRUCTURE.md).
