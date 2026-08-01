"""Unit tests — no database required.

These tests exercise pure logic without database access:
- Rules calculations (proficiency bonus, ability modifiers, AC)
- Policy decisions (approval rules, visibility policies)
- Validation (command payload validation, domain invariants)
- Utility functions

Mark tests with @pytest.mark.unit for explicit filtering.

See: docs/DEVELOPMENT.md §6 (Testing layers)
"""
