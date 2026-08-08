"""Database tests — PostgreSQL required (a local PostgreSQL 18 server by
default; CI runs the same suite against AWS dev RDS as the merge gate).

These tests exercise database-level behavior:
- Constraints (CHECK, UNIQUE, FOREIGN KEY, EXCLUDE)
- Triggers and stored functions
- Subtype consistency (class-table inheritance)
- Same-world invariants
- State uniqueness per timeline
- Branch behavior and timeline inheritance
- Event/state atomicity
- Quest transition rules

Every nontrivial constraint must have a positive AND a negative test per §32.1.
Build test data through commands, not raw inserts, per §32.3.

Mark tests with @pytest.mark.database for explicit filtering.

See: docs/DEVELOPMENT.md §6 (Testing layers)
     docs/DATABASE_CONVENTIONS.md §32 (Testing conventions)
"""
