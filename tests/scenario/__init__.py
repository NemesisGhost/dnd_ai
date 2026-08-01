"""Scenario tests — cross-domain flows.

These tests validate end-to-end flows across multiple domains using a real
PostgreSQL container:
- The full vertical slice from docs/PLAN.md §24 (dungeon scenario)
- Campaign branching and timeline isolation
- Quest advancement from events
- Knowledge discovery and propagation
- NPC portrayal context assembly
- Import and approval workflows

These are acceptance tests — they prove the architecture supports actual play.

Mark tests with @pytest.mark.scenario for explicit filtering.

See: docs/DEVELOPMENT.md §6 (Testing layers)
     docs/PLAN.md §24 (Vertical-slice acceptance scenario)
"""
