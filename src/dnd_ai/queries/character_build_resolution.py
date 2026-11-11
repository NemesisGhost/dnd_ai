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
3. **Administrative baseline fallback.** Walk ancestors for the initial
   administrative state (`last_event_id IS NULL`). Since checkpoint 15.2B-2,
   `activate_character_build` makes the first activation on untouched state
   administrative and records every later activation through a causal event.
   If an ancestor has since activated another build by event, recover its
   baseline from the `previous_value` of its earliest build effect.

   Arbitrary later event-less rewrites bypass that history and are not made
   branch-safe by this fallback. Use the supported activation command rather
   than rewriting an ancestor's administrative row after branching. See
   docs/api/CHARACTER_SHEET.md for the contract.

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
        # The ancestor changed the build by event only after the branch point (step
        # 2 found nothing at or before it), so what it replaced is the baseline this
        # timeline branched from: the `previous_value` of its earliest build effect.
        # (Checkpoint 15.2B-2: `activate_character_build` records that previous
        # value on every event activation.)
        earliest = connection.execute(
            text("""
                SELECT ee.previous_value
                FROM narrative.events e
                JOIN narrative.event_effects ee ON ee.event_id = e.event_id
                JOIN core.world_times wt ON wt.world_time_id = e.world_time_id
                WHERE e.timeline_id = :timeline
                  AND ee.target_entity_id = :character
                  AND ee.target_component = 'character_build_id'
                ORDER BY wt.sort_key ASC, e.created_at ASC
                LIMIT 1
            """),
            {"timeline": parent_timeline_id, "character": character_id},
        ).one_or_none()
        if earliest is not None:
            return uuid.UUID(earliest[0]) if earliest[0] is not None else None
        current_timeline_id = parent_timeline_id
