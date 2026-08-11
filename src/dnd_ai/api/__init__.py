"""API layer — authentication, authorization, input validation, routing,
and response shaping (docs/architecture/SYSTEM_ARCHITECTURE.md §5.2). No
domain rules belong here; handlers call `dnd_ai.commands`/`dnd_ai.queries`
(docs/DEVELOPMENT.md §9).
"""
