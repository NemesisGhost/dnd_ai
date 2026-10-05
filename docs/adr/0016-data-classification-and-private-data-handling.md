# ADR 0016: Data classification and private-data handling

- **Status**: Accepted
- **Date**: 2026-10-05
- **Builds on**: [ADR 0006](0006-ai-proposes-but-does-not-own-canon.md), [ADR 0007](0007-separate-knowledge-from-truth.md), [ADR 0009](0009-separate-owning-role-from-login-roles.md), [ADR 0015](0015-typed-world-content-authoring.md).
- **Related**: [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §24, §27; PLANv2 §16.3–16.4, §17.4, §18 item 12.

## Context

Phase 15 completion found current defects in how authored content moved through audit, replay storage, previews, and the reporting role: narrative text was copied into `audit.change_log.changed_fields`, full GM-only authoring views were stored as idempotency replay bodies, audience previews were unaudited, and `app_read_only` could read credentials, tokens, and every private store. Phase 16 will add player-private content (notes, theories, discussions) for which none of those paths may ever carry values. The platform needs one vocabulary and one set of handling rules, established before Phase 16 builds on them, without implementing any player-private feature.

## Decision

1. **Seven data classes** (`dnd_ai.domain.data_classification.DataClass`): `PUBLIC_WORLD`, `CAMPAIGN_VISIBLE`, `GM_ONLY`, `CHARACTER_VISIBLE`, `PARTY_VISIBLE`, `PLAYER_PRIVATE`, `SECRET`, plus `STRUCTURAL` for identifiers, codes, enumerations, and numbers. Every TEXT/JSONB column of an authored or state table has a class in `COLUMN_CLASSES`; a live-schema test fails on an unclassified new column. `PLAYER_PRIVATE` is reserved: no Phase 15 column carries it.
2. **Handling by class**

   | Concern | PUBLIC / CAMPAIGN | GM_ONLY | CHARACTER / PARTY | PLAYER_PRIVATE (contract for Phase 16) | SECRET |
   |---|---|---|---|---|---|
   | Authorization | `campaign.view` + lifecycle gating | `canon.edit` | perspective capability | owner/participants only; GM roles never | not readable through any API |
   | API projection | default | field omitted without `canon.edit` | only through the matching perspective | owner/participant projections | never |
   | Audit metadata | ids, codes, names, numbers; prose `{"redacted": true}` | same | same | field names only; never values or lengths | event only, never values |
   | Idempotency storage | receipt | receipt | receipt | receipt (mandatory) | never stored |
   | Logs, errors, metrics, traces | ids and codes | ids | ids | ids | never |
   | Preview | via a reviewed adapter | n/a | via a reviewed adapter | **never previewable** without an explicit new ADR | never |
   | Export (future) | included | GM export only | the knower's holders | owner only | excluded |
   | Deletion | archive (rule 9) | archived with record | follows state history | owner-requested deletion honoured | expiry/revocation, then purge |
   | Reporting role | reviewed views only | none | none | none | none |

3. **Audit is accountability, never content history.** Typed authoring commands record *that* a field changed. The builders are default deny (only `AUDIT_STRUCTURAL_FIELDS` keep values). Canonical prior-version history is a separate, GM-only store (checkpoint 15.2R).
4. **Idempotency replay bodies are receipts** (ids, `row_version`, flags). Any future mutation that touches `PLAYER_PRIVATE` content must be receipt-only.
5. **Previews are a closed, read-only registry** (`PREVIEW_ADAPTERS`). Each adapter declares a data-class ceiling that may not include `PLAYER_PRIVATE` or `SECRET` (enforced at construction). Every preview request that passes the actor's own authorization writes one metadata-only `sensitive_read` audit row (D-4: `audit.change_log`, not a new table).
6. **Reporting access is deny by default** (migration 115). Reporting, if ever needed, goes through reviewed views in a `reporting` schema; administrator and migration authority is separate from reporting access.
7. **Policy defaults (D-6)**
   - *Retention:* canonical content, events, state, and audit live as long as the world; revisions as long as the entity; completed idempotency rows 30 days; used or expired tokens and ended browser sessions 30 days (operator purge; the purge scripts are not part of this phase).
   - *Deletion:* persistent world records are archived, not deleted; physical deletion only for unreferenced drafts and documented legal removal. Account deletion is a Phase 16/17 requirement recorded here, not built.
   - *Export:* none in Phase 15. Any future export applies the reader's projection; a GM export never includes `PLAYER_PRIVATE`.
   - *Backups:* contain all data, including pre-scrub values until retired; restore testing is Phase 17.
   - *Logs, metrics, traces:* identifiers, codes, durations, and outcomes only; never request bodies, field values, statements, notes, or tokens.
   - *Host administrator:* the machine or database administrator can inspect stored data. The product promises application-level role privacy, not secrecy from the host administrator.
8. **Outcomes of related decisions:** D-3 (GM-only free text: `origin_notes`, `condition_notes`, `events.details`, hidden from callers without `canon.edit`), D-4 (`sensitive_read` in `audit.change_log`), D-27 (receipts), D-5 (deny-by-default `app_read_only`) are implemented. D-2 and D-28 (scrubbing rows written before this decision) are decided separately at checkpoint 15.2A-4 and recorded there as an addendum.

## Consequences

- A new free-text column cannot ship without a classification, and a new previewable resource cannot ship without a reviewed adapter.
- Audit history no longer answers "what did the text say before the edit"; prior versions come from the revision store, and until that exists there is no prior-version feature.
- Pre-existing audit and idempotency rows keep their old content until the owner-gated scrub; the limitation is disclosed in PHASE15_VERIFICATION.
- Phase 16 inherits these rules; it may add `collaboration` tables only with classifications, receipt-only mutations, no reporting grant, and no preview adapter without a new decision.

## References

- `src/dnd_ai/domain/data_classification.py`, `src/dnd_ai/api/preview.py`
- `tests/database/test_data_classification_schema.py`, `tests/database/test_private_data_not_stored.py`, `tests/database/test_reporting_role_boundary.py`, `tests/unit/test_privacy_guards.py`
- [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §24, §27; [SYSTEM_ARCHITECTURE.md](../architecture/SYSTEM_ARCHITECTURE.md) §19
