"""Branch-effective resolution of `campaign.character_state.character_build_id`.

`campaign.character_state` is a current-value snapshot table — one row per
`(timeline_id, character_id)`, with no interval/history columns (docs/
architecture/DATABASE_MODEL.md §17). Per docs/ENTITY_LIFECYCLE.md §9 rule 6,
"the branch creates new typed state only when it diverges" — a freshly
branched child timeline has no local `character_state` row at all until
something on that timeline actually changes it. Reading a character's sheet
on such a child must not return "no active build": it must resolve the same
build its parent had selected *as of the branch point* — but it must also
never leak a change the parent made *after* that point (CLAUDE.md rule 7).

Resolution, in order:

1. **Local state wins.** If `timeline_id` itself has a `character_state` row
   for `character_id`, its `character_build_id` is authoritative — even
   when `NULL` ("this timeline explicitly has no active build selected"),
   and regardless of ancestry. A timeline that has diverged never looks at
   its parent again for this component.
2. **Event-linked ancestry.** Failing that, reconstruct the value from
   `narrative.event_effects` rows with `target_component =
   'character_build_id'` for this character, restricted to
   `campaign.effective_events(timeline_id)` — the existing branch-aware
   effective-history function (revision 059) that already walks
   `parent_timeline_id` and bounds each ancestor's own history at the point
   the next timeline down actually branched off it. The latest such effect
   (by its event's world-time `sort_key`) is the value effective on this
   timeline. This is the only way to recover a value from an ancestor whose
   row has since changed again: the *current* row could reflect a change
   made after the branch, but the bounded event history cannot.
3. **Administrative baseline fallback.** No command in this codebase yet
   changes `character_build_id` through a causal event — the only writer
   today is administrative (dev/setup tooling, `last_event_id IS NULL`),
   which CLAUDE.md rule 6 explicitly allows ("or explicit administrative
   source"). An administrative write has no recorded time, so it cannot be
   bounded against a branch point the way an event can. Since in current
   practice such a write only ever happens once, at character setup, before
   any branching involving that character could occur, an ancestor's
   administrative row is treated as safe to inherit unconditionally: walk
   `parent_timeline_id` one level at a time and return the first ancestor
   that has its own row with `last_event_id IS NULL` (its `character_build_id`,
   possibly `NULL`, wins and stops the walk — same "local, even if NULL,
   wins" rule as step 1).

   This is a genuine, documented schema limitation, not a design choice:
   if a *second* administrative write ever changed an ancestor's build
   after a descendant had already branched off it, this fallback could not
   detect that and would incorrectly treat the new value as always having
   been true. Closing this gap for good requires routing every
   `character_build_id` change through a causal event (mirroring the
   existing HP/condition/resource commands in
   `dnd_ai.commands.character_state`) — no such "select active build"
   command exists yet because nothing in the product calls it; see
   docs/PHASE13D_CHARACTER_SHEET_BACKEND.md for the full writeup.

Steps 2 and 3 only ever run when step 1 finds no local row at all, and step
3 only runs when step 2's bounded event search finds nothing — an ancestor
with event-linked history for this component is always resolved through the
sound, bounded path first.
"""

import uuid

from sqlalchemy import Connection, text


def resolve_effective_character_build_id(
    connection: Connection, *, character_id: uuid.UUID, timeline_id: uuid.UUID
) -> uuid.UUID | None:
    """The active `character.character_builds.character_build_id` for
    `character_id` as of `timeline_id`, resolved per this module's own
    docstring. `None` means "no active build" — a legitimate, successful
    result (empty sheet), not an error."""
    local_row = (
        connection.execute(
            text("""
                SELECT character_build_id FROM campaign.character_state
                WHERE timeline_id = :timeline AND character_id = :character
            """),
            {"timeline": timeline_id, "character": character_id},
        )
        .mappings()
        .one_or_none()
    )
    if local_row is not None:
        build_id = local_row["character_build_id"]
        return uuid.UUID(str(build_id)) if build_id is not None else None

    event_value = connection.execute(
        text("""
            SELECT ee.new_value
            FROM campaign.effective_events(:timeline) e
            JOIN narrative.event_effects ee ON ee.event_id = e.event_id
            JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
            WHERE ee.target_entity_id = :character
              AND ee.target_component = 'character_build_id'
            ORDER BY wt.sort_key DESC, e.created_at DESC
            LIMIT 1
        """),
        {"timeline": timeline_id, "character": character_id},
    ).scalar()
    if event_value is not None:
        return uuid.UUID(event_value)

    current_timeline_id = timeline_id
    while True:
        parent_timeline_id = connection.execute(
            text("SELECT parent_timeline_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": current_timeline_id},
        ).scalar()
        if parent_timeline_id is None:
            return None
        admin_row = (
            connection.execute(
                text("""
                    SELECT character_build_id FROM campaign.character_state
                    WHERE timeline_id = :timeline AND character_id = :character
                      AND last_event_id IS NULL
                """),
                {"timeline": parent_timeline_id, "character": character_id},
            )
            .mappings()
            .one_or_none()
        )
        if admin_row is not None:
            build_id = admin_row["character_build_id"]
            return uuid.UUID(str(build_id)) if build_id is not None else None
        current_timeline_id = parent_timeline_id
