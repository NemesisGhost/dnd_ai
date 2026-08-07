"""Command handlers — the only application-layer path that mutates state.

See docs/architecture/SYSTEM_ARCHITECTURE.md §5.3/§6 and docs/DEVELOPMENT.md
§9 for the layering and per-command requirements this package follows: one
PostgreSQL transaction per world change, a causal event alongside any
narratively significant state change (CLAUDE.md rule 6), external calls
deferred until after commit.
"""
