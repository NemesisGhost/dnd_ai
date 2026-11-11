# Documentation

Start with the topic you need. Current behavior belongs in the topic references;
the roadmap describes intended delivery, and dated evidence describes only the run recorded.

| Question | Maintained reference |
|---|---|
| What is the product? | [Project README](../README.md) |
| What is implemented and what blocks delivery? | [Project status](PROJECT_STATUS.md) |
| What comes next? | [Roadmap](PLANv2.md), [outstanding work](BACKLOG.md) |
| How do I develop and verify a change? | [Development](DEVELOPMENT.md) |
| What does a domain term mean? | [Domain model](DOMAIN_MODEL.md) |
| Which tables and invariants apply? | [Database model](architecture/DATABASE_MODEL.md), [database conventions](DATABASE_CONVENTIONS.md) |
| How do records change? | [Entity lifecycle](ENTITY_LIFECYCLE.md) |
| Where does code belong? | [System architecture](architecture/SYSTEM_ARCHITECTURE.md) |
| How do read APIs work? | [Read API](api/READ_API.md), [character sheet](api/CHARACTER_SHEET.md) |
| Who may access or change something? | [Access control](api/ACCESS_CONTROL.md), [audit history](AUDIT_HISTORY_API.md) |
| How should the portal behave and look? | [UI design](UI_DESIGN.md), [style guide](UI_STYLE_GUIDE.md) |
| How is production intended to run? | [Local deployment](LOCAL_DEPLOYMENT.md) |
| How do I recover data or administrator access? | [Database recovery](operations/DATABASE_RECOVERY.md), [administrator recovery](operations/PLATFORM_ADMINISTRATOR_RECOVERY.md) |
| What about optional AWS infrastructure? | [AWS RDS reference](INFRASTRUCTURE.md) |
| How do we review findings? | [Issue grading](ISSUE_GRADING_RUBRIC.md) |
| Why was an architectural choice made? | [ADRs](adr/) |
| What was verified historically? | [Delivery history and retired-source map](DELIVERY_HISTORY.md) |

## Active implementation and acceptance

- [Outstanding work](BACKLOG.md) consolidates the five retired local plans, R01–R18, current package status, unresolved defects, scope decisions and acceptance gates (reviewed at `d51e38a`, 2026-11-11).
- [Context-navigation correction plan](PHASE15_CONTEXT_NAVIGATION_CORRECTION_PLAN_2026-11-11.md) scopes the Infobox timeline read gates, campaign-only timeline navigation (CN-1), the meaningful-choice rule (CN-2) and stale World option reconciliation; the contract is [UI_DESIGN §4.8.12](UI_DESIGN.md#4812-context-navigation-correction-read-gates-destinations-and-meaningful-choice-approved-2026-11-11-implemented). Implemented through `6cdc68b`, with independent review recorded as PASS WITH NONBLOCKING VERIFICATION LIMITATION; real-browser checks and retained follow-ups remain.
- [P03-A](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md) and its [A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) remain active handoff inputs. Read the latest dated implementation/review entry as well as the opening summary.
- [P03-A A5 design](PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md) specifies the OD-18 campaign-scoped player profile: storage, GM reads and publication of a selected field through A2 provenance (slices A5a–A5c, migrations 147–148). Proposed; owner decisions D13–D18 gate implementation.
- [R19 foundation plan](R19_FOUNDATION_IMPLEMENTATION_PLAN.md) retains pending implementation and coordination gates. Accepted ADRs do not prove implementation.
- Phase 14/15: [journey](PHASE14_15_HOWTO_FIRST_CAMPAIGN.md), [companion scenarios](PHASE14_15_COMPANION_SCENARIOS.md), [coverage](PHASE14_15_COVERAGE_MATRIX.md), [results and decisions](PHASE14_15_ACCEPTANCE_LEDGER.md), [defects](PHASE14_15_DEFECT_REGISTER.md), [environment](PHASE14_15_ACCEPTANCE_ENVIRONMENT.md), and [Phase 15 verification](PHASE15_VERIFICATION.md).

## Maintenance rules

Keep one current description of each contract. Link to it from plans instead of copying it.
Record outstanding work by stable ID in the backlog or defect register. Record tests with
their SHA, environment and method; code review, automated tests, browser checks, assistive
technology and owner acceptance are separate evidence. A historical pass never becomes a
fresh pass through documentation editing.

Closed execution diaries live in Git history, indexed by DELIVERY_HISTORY. Short legacy
filename pointers remain only where active handoffs or numerous source citations still
depend on them; they do not create a second authority. Delete a pointer when its callers
have been migrated. New documentation should use the maintained topic paths above.
