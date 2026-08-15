"""Query services (docs/PLAN.md Phase 10 deliverable "query services for the
effective dungeon, character, quest, relationship, inventory, encounter, and
knowledge state required by the vertical slice").

Mirrors `dnd_ai.commands`' package shape: framework-free, connection-taking
functions returning plain dataclasses, never FastAPI/pydantic types
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.4) — `dnd_ai.api` is the only
layer that knows about HTTP. Per §6 of that document, query services read
through optimized views/read models and never mutate domain state; unlike
`dnd_ai.commands`, there is no `_..._impl`/engine-wrapper split here, since a
read has no transaction-boundary reason to open one — callers always supply
a `Connection` already scoped to the request.
"""
