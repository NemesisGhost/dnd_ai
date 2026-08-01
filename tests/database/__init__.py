"""Database tests — PostgreSQL container required.

These tests exercise database-level behavior using testcontainers:
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
