# D&D AI documentation

Use the portal to author shared world content, operate a campaign and show each player the material their audience can read. Start with the tutorial if this is your first campaign.

## Tutorials

[Run your first session](tutorials/first-campaign.md) walks from a bootstrapped account to a completed session in a new world.

## How-to guides

| To do this | Open |
|---|---|
| Install the API and portal, activate the first account | [Start locally](operations/start-locally.md) |
| Work on the backend, write migrations or run checks | [Development](DEVELOPMENT.md) · [Seed data](../database/seeds/README.md) |
| Run or build a client | [Portal](../portal/README.md) · [Package and pair Foundry](../foundry-module/README.md) |
| Operate a deployment or plan production ingress | [Deployment](operations/deployment.md) · [Optional AWS infrastructure](operations/optional-aws.md) |
| Restore a database or regain administrative access | [Database recovery](operations/DATABASE_RECOVERY.md) · [Administrator recovery](operations/PLATFORM_ADMINISTRATOR_RECOVERY.md) |

## Reference

| Subject | Contract |
|---|---|
| HTTP requests, responses, authority and transaction handling | [API operation catalog](api/operations.md) · [Read projections](api/READ_API.md) · [Character sheet](api/CHARACTER_SHEET.md) |
| Authentication, access management, profiles and final authorization | [Access control](api/ACCESS_CONTROL.md) · [Audit history](reference/audit-history.md) |
| PostgreSQL schema, naming and commands | [Table inventory](reference/tables.md) · [Logical model](architecture/DATABASE_MODEL.md) · [Database conventions](DATABASE_CONVENTIONS.md) · [Entity lifecycle](ENTITY_LIFECYCLE.md) |
| Environment, AI settings and integrations | [Runtime configuration](reference/runtime.md) · [Environment template](../.env.example) |
| Portal navigation, interaction and visual rules | [Screen behavior](reference/portal-behavior.md) · [Navigation](reference/portal-navigation.md) · [Style guide](reference/portal-style.md) |
| Documentation ownership and editorial rules | [Documentation standard](standard.md) |

## Explanation

- [Worlds, people and play](explanation/worlds-and-play.md) explains scope, control, publication and discovery.
- [Domain model](DOMAIN_MODEL.md) defines the vocabulary. [System architecture](architecture/SYSTEM_ARCHITECTURE.md) describes layering and transactions. The [dungeon scenario](architecture/DUNGEON_FLOW.md) ties the domains together.
- [Architecture decisions](adr/) preserve rationale, superseded choices and accepted future requirements.

## Delivery and evidence

- [Work register](delivery/work-register.md) for the single maintained register, current obligations and ID migration crosswalk. [Roadmap](delivery/roadmap.md) for phase order and dependencies.
- [Character work](delivery/shared-characters.md), [ownership design](delivery/ownership-design.md), [player profiles](delivery/player-profile-design.md), [context navigation](delivery/context-navigation.md) and [rules foundations](delivery/rules-foundations.md) for detailed scope and decisions.
- [First-campaign acceptance script](delivery/first-campaign-acceptance.md), [companion scenarios](delivery/companion-scenarios.md), [coverage matrix](delivery/coverage.md) and [environment](delivery/acceptance-environment.md) for rehearsals. [Ledger](delivery/acceptance-ledger.md) for recorded outcomes.
- [Defects](delivery/defects.md), [grading rubric](delivery/grading.md), [Phase 15 verification](delivery/phase-15-verification.md), [delivery history](delivery/history.md) and [migration record](delivery/migration.md) for traceability.
