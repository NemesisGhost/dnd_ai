# D&D AI coding instructions

Start with [CLAUDE.md](../CLAUDE.md), then use the [documentation index](../docs/README.md)
to retrieve only the affected domain, schema, lifecycle, architecture and development sections.
Use [PROJECT_STATUS](../docs/PROJECT_STATUS.md) for recorded current delivery state and
[PLANv2](../docs/PLANv2.md) for future order. Active plans are linked from the index.

PostgreSQL is canonical; clients use the API; AI proposes changes through authorized
commands. Follow the full rules and linked authorities in CLAUDE.md rather than a
duplicated summary here. Existing working data is not disposable because an old
architecture restart occurred. Follow current preservation, migration and recovery policy.

The API and React portal are implemented. Self-hosted Compose and containerized PostgreSQL
CI are the supported path. Optional AWS operations are documented separately. Keep changes
scoped to the task; preserve unrelated working changes and commit only your own files/hunks.
