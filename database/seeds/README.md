# Seed data directory
#
# Lookup-table seed data as YAML files, one per table.
# Applied through Alembic revisions via src/dnd_ai/persistence/seeds.py
#
# Naming convention: <schema>.<table>.yaml
#
# Example: core.canon_statuses.yaml
#
# Format:
# - code: draft
#   name: Draft
#   description: Not yet ready for review
# - code: proposed
#   name: Proposed
#   description: Submitted for GM or validation review
#
# See: docs/DATABASE_CONVENTIONS.md §25.4 (Seed data)
