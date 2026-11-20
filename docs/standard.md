# Maintaining the documentation

Start from the reader's question. Give each maintained rule one owner and link to it from plans, guides and component READMEs. Keep root README short and register each maintained subject in the [documentation hub](README.md).

| Type | Where it belongs | What the reader gets |
|---|---|---|
| Tutorial | `docs/tutorials/` | A complete journey with prerequisites, actions and an observable result |
| How-to | `docs/operations/`, the development guide or a component README | Steps for one task, including configuration scope, refusal cases and recovery where relevant |
| Reference | `docs/reference/`, `docs/api/` and established schema/lifecycle contracts | Exact names, units, scope, supported behavior and limitations |
| Explanation | `docs/explanation/`, domain and architecture guides | Concepts, relationships and design tradeoffs |
| Decision | `docs/adr/` | A durable decision, alternatives, rationale, status and any superseding decision |
| Delivery and evidence | `docs/delivery/` | Ordered scope, a single work register, dated reviews, acceptance obligations and executed results |

**Describe status at the point of use.** Use *implemented* for behavior evidenced in source, *accepted requirement* for approved intent awaiting implementation, *proposal* for an undecided design, *deferred* for an explicit postponement, and *historical* for an observation tied to a baseline. Identify an unresolved discrepancy and its register entry. Record independent review, browser or integration runs and owner acceptance independently. Only the owner can dispose of an owner acceptance gate.

**Keep delivery traceable.** Use Phase → Checkpoint → Slice → Task where adopted. Keep the existing order, dependencies and stable IDs. Review IDs such as R01 and Fable C1 trace findings into that hierarchy. The roadmap owns order, the work register owns outstanding work, the defect register owns defect evidence and the acceptance ledger owns runs. Preserve dates, SHAs, failed runs, reruns and limitations.

**Link to the subject.** Use repository-relative Markdown links, including the heading fragment when citing a section. For old commands or quoted evidence, retain the original spelling and identify its execution baseline. Use a commit-pinned original for historical section numbers. Keep private evidence out of shared examples. Use placeholders and paths relative to the checkout.

**When behavior changes**, update the owning contract and affected guides in the same change. Compare route method/path pairs with OpenAPI and the registered handlers, and schema names with imported metadata and Alembic revisions. Check links and fragments from all affected entry points. A current source inventory establishes presence. A passing acceptance claim needs a run or explicit decision at an identified revision.

From the checkout root, run `uv run python scripts/check_documentation.py` to compare local Markdown links, API catalog coverage and the declared table inventory. It uses the project environment and opens no database.
