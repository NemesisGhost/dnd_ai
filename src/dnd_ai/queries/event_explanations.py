"""Event explanations: what happened, to whom, and when (Phase 15 checkpoint CP-9a, read side).

A recorded event already carries its facts: participants and effects (the typed-state change with
its previous and new value), the effective in-world time, the real recording timestamp, an
optional session, cause rows and correction links. This module reads them back as small typed
explanations, one adapter per effect family:

- party membership (`party_member_joined` / `party_member_left`): the character and the party;
- character build (`character_build_activated`): previous and new build labels, only for a reader
  allowed the full tier of that character (decision DR-6), otherwise a generic "build changed";
- campaign clock (`time_advanced` / `time_corrected`): previous and new in-world time;
- current location and travel: delegated to `session_travel`, which owns the leg logic.

Nothing here writes, and an event is never invented: the administrative first build activation and
no-op commands record no event, so there is nothing to explain. Audit logs and revision snapshots
are not domain history and are not read.

Audience, applied here and nowhere else for these surfaces:

- Every character goes through `discoverable_entity_ids` with the caller's `WorldEntityVisibility`
  (the World Explorer rule, entity denies included). A character the caller cannot discover
  becomes an `unavailable` reference: no id, no name, no count.
- Build labels need `may_read_build` for that character; a build that does not belong to the
  event's character is `unavailable`.
- A party must belong to the caller's campaign and be readable (an archived party is
  `unavailable` to anyone without `canon.edit`).
- World times must belong to the event's world.
- A related event (cause, clock chain, correction) must be on the caller's own timeline, which also
  stops a branch seeing a parent's post-branch history. Cause links to events the caller cannot
  read are omitted; correction links to events the caller cannot open stay as an `unavailable`
  reference, because the visible correcting or replacement event already says a correction exists.
- The correction reason is `canon.edit` only.
- A session reference is present only when the caller may view that session.

Names are the entity's current label, not a snapshot of what it was called when the event
happened. `unrecorded` means the event itself records no value (a first join has no earlier
party); `unavailable` means a value exists that the caller may not see or that no longer
resolves. Neither carries an id or a name.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.campaign_clock import (
    CLOCK_EVENT_ADVANCED,
    CLOCK_EVENT_CORRECTED,
    CLOCK_EVENT_TYPES,
)
from dnd_ai.domain.character_builds import BUILD_COMPONENT, BUILD_EVENT_ACTIVATED
from dnd_ai.domain.party_authoring import (
    PARTY_ACTIVE,
    PARTY_MEMBER_JOINED,
    PARTY_MEMBER_LEFT,
    PARTY_MEMBERSHIP_COMPONENT,
)

from .campaign_clock import clock_display
from .session import SessionEventView
from .session_travel import TRAVEL_EVENT_TYPE, SessionTravelEntry, list_session_travel
from .world_explorer import WorldEntityVisibility, discoverable_entity_ids

NAMED = "named"
UNRECORDED = "unrecorded"
UNAVAILABLE = "unavailable"

FAMILY_PARTY_JOINED = "party_member_joined"
FAMILY_PARTY_LEFT = "party_member_left"
FAMILY_BUILD = "character_build_activated"
FAMILY_CLOCK_ADVANCED = "campaign_clock_advanced"
FAMILY_CLOCK_CORRECTED = "campaign_clock_corrected"
FAMILY_LOCATION = "location"
FAMILY_TRAVEL = "travel"
# A recorded event with no adapter: still carries when it happened and its links.
FAMILY_OTHER = "other"

BUILD_DETAIL_FULL = "full"
BUILD_DETAIL_GENERIC = "generic"

# How an advance recorded under the CP-9b contract was caused. Advances recorded earlier have no
# marker and so no origin: they are never guessed to have been manual.
ORIGIN_MANUAL = "manual"
ORIGIN_EVENT_CAUSE = "event_cause"

REL_FOLLOWS_CLOCK = "follows_previous_clock_change"
REL_CORRECTS_CLOCK = "corrects_clock_change"
REL_CORRECTED_BY_CLOCK = "corrected_by_clock_change"
REL_CAUSED_BY = "caused_by"
REL_CORRECTED_BY = "corrected_by"
REL_REPLACED_BY = "replaced_by"
REL_CORRECTS = "corrects"
REL_REPLACES = "replaces"

_CLOCK_TYPES = CLOCK_EVENT_TYPES
_RELATION_ORDER = {
    relation: rank
    for rank, relation in enumerate(
        (
            REL_FOLLOWS_CLOCK,
            REL_CORRECTS_CLOCK,
            REL_CAUSED_BY,
            REL_CORRECTED_BY_CLOCK,
            REL_CORRECTED_BY,
            REL_REPLACED_BY,
            REL_CORRECTS,
            REL_REPLACES,
        )
    )
}
_LOCATION_COMPONENT = "current_location_id"


@dataclass(frozen=True)
class ExplanationRef:
    state: str
    kind: str
    entity_id: uuid.UUID | None = None
    name: str | None = None
    # Whether the caller may follow the reference to its own page.
    openable: bool = False


@dataclass(frozen=True)
class ExplanationRelation:
    relation: str
    event: ExplanationRef
    # Correction reason: `canon.edit` only.
    reason: str | None = None


@dataclass(frozen=True)
class ExplanationSession:
    session_id: uuid.UUID
    session_number: int
    title: str | None


@dataclass(frozen=True)
class ExplanationClockTime:
    state: str
    text: str | None = None


@dataclass(frozen=True)
class EventExplanation:
    event_id: uuid.UUID
    family: str
    # Effective in-world time, formatted by the campaign calendar; recorded real time apart.
    in_world_time: str
    recorded_at: datetime
    subject: ExplanationRef | None = None
    party: ExplanationRef | None = None
    build_detail: str | None = None
    previous_build: ExplanationRef | None = None
    new_build: ExplanationRef | None = None
    previous_time: ExplanationClockTime | None = None
    new_time: ExplanationClockTime | None = None
    # Clock advances only (CP-9b): `manual`, `event_cause`, or None for an earlier advance.
    advance_origin: str | None = None
    # The GM's explanation for the members who may view this event (campaign-visible), never
    # `events.details`.
    member_explanation: str | None = None
    travel: SessionTravelEntry | None = None
    session: ExplanationSession | None = None
    relations: tuple[ExplanationRelation, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExplanationAudience:
    """The caller, resolved once by the API layer from the `AccessContext`."""

    campaign_id: uuid.UUID
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    visibility: WorldEntityVisibility
    can_edit: bool
    # Full tier of that character (GM included) and not entity-denied.
    may_read_build: Callable[[uuid.UUID], bool]
    may_open_character: Callable[[uuid.UUID], bool]
    may_view_session: Callable[[uuid.UUID], bool]
    # The authoring read for people who edit canon: related events of the own timeline are all
    # nameable, including voided ones the correction surface is about.
    authoring: bool = False


def _as_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _unavailable(kind: str) -> ExplanationRef:
    return ExplanationRef(UNAVAILABLE, kind)


def _unrecorded(kind: str) -> ExplanationRef:
    return ExplanationRef(UNRECORDED, kind)


def _family(type_code: str, components: set[str]) -> str:
    if type_code == PARTY_MEMBER_JOINED:
        return FAMILY_PARTY_JOINED
    if type_code == PARTY_MEMBER_LEFT:
        return FAMILY_PARTY_LEFT
    if type_code == BUILD_EVENT_ACTIVATED:
        return FAMILY_BUILD
    if type_code == CLOCK_EVENT_ADVANCED:
        return FAMILY_CLOCK_ADVANCED
    if type_code == CLOCK_EVENT_CORRECTED:
        return FAMILY_CLOCK_CORRECTED
    if type_code == TRAVEL_EVENT_TYPE:
        return FAMILY_TRAVEL
    if _LOCATION_COMPONENT in components:
        return FAMILY_LOCATION
    return FAMILY_OTHER


def explain_events(
    connection: Connection,
    *,
    event_ids: Sequence[uuid.UUID],
    audience: ExplanationAudience,
) -> dict[uuid.UUID, EventExplanation]:
    """One explanation per event of the audience's own timeline among `event_ids`. An id that is
    not an event of that timeline and world is absent from the result (callers have already
    applied the draft/voided rules for the event itself)."""
    if not event_ids:
        return {}
    ids = sorted(set(event_ids))
    events = connection.execute(
        text("""
            SELECT ev.event_id, ev.session_id, ev.world_time_id, ev.created_at,
                   et.code AS type_code, es.code AS status_code
            FROM narrative.events ev
            JOIN core.entities ce ON ce.entity_id = ev.event_id
            JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
            JOIN narrative.event_statuses es ON es.event_status_id = ev.event_status_id
            WHERE ev.event_id = ANY(CAST(:ids AS uuid[]))
              AND ev.timeline_id = :t AND ce.world_id = :w
        """),
        {"ids": ids, "t": audience.timeline_id, "w": audience.world_id},
    ).all()
    if not events:
        return {}
    known = [e.event_id for e in events]
    effects_by_event: dict[uuid.UUID, list[Any]] = {}
    for eff in connection.execute(
        text("""
            SELECT event_id, target_entity_id, target_component, previous_value, new_value
            FROM narrative.event_effects
            WHERE event_id = ANY(CAST(:ids AS uuid[]))
            ORDER BY created_at, event_effect_id
        """),
        {"ids": known},
    ):
        effects_by_event.setdefault(eff.event_id, []).append(eff)
    participants_by_event: dict[uuid.UUID, list[uuid.UUID]] = {}
    for part in connection.execute(
        text("""
            SELECT event_id, participant_entity_id FROM narrative.event_participants
            WHERE event_id = ANY(CAST(:ids AS uuid[])) ORDER BY event_participant_id
        """),
        {"ids": known},
    ):
        participants_by_event.setdefault(part.event_id, []).append(part.participant_entity_id)

    resolver = _Resolver(connection, audience)
    families = {
        e.event_id: _family(
            str(e.type_code),
            {str(f.target_component) for f in effects_by_event.get(e.event_id, [])},
        )
        for e in events
    }
    for e in events:
        resolver.want_event_effects(
            families[e.event_id],
            effects_by_event.get(e.event_id, []),
            participants_by_event.get(e.event_id, []),
        )
    resolver.prefetch()

    location_ids = [
        e.event_id for e in events if families[e.event_id] in (FAMILY_LOCATION, FAMILY_TRAVEL)
    ]
    travel = _travel_entries(
        connection, audience, [e for e in events if e.event_id in location_ids]
    )
    relations = _relations(connection, audience, events)
    advances = [e.event_id for e in events if families[e.event_id] == FAMILY_CLOCK_ADVANCED]
    advance_details = _advance_details(connection, advances)
    # The member-safe text goes only where the event itself may be named, whichever surface asks.
    explainable = set(_event_refs(connection, audience, advances))

    result: dict[uuid.UUID, EventExplanation] = {}
    for e in events:
        family = families[e.event_id]
        effects = effects_by_event.get(e.event_id, [])
        parts = participants_by_event.get(e.event_id, [])
        base: dict[str, Any] = {
            "event_id": e.event_id,
            "family": family,
            "in_world_time": resolver.event_time(e.world_time_id),
            "recorded_at": e.created_at,
            "session": resolver.session(e.session_id),
            "relations": relations.get(e.event_id, ()),
        }
        if family in (FAMILY_PARTY_JOINED, FAMILY_PARTY_LEFT):
            base.update(resolver.party_fields(effects, parts))
        elif family == FAMILY_BUILD:
            base.update(resolver.build_fields(effects, parts))
        elif family in (FAMILY_CLOCK_ADVANCED, FAMILY_CLOCK_CORRECTED):
            base.update(resolver.clock_fields(effects))
            origin, explanation = advance_details.get(e.event_id, (None, None))
            base["advance_origin"] = origin
            base["member_explanation"] = explanation if e.event_id in explainable else None
        elif family in (FAMILY_LOCATION, FAMILY_TRAVEL):
            base["travel"] = travel.get(e.event_id)
        result[e.event_id] = EventExplanation(**base)
    return result


class _Resolver:
    """Batched, cached lookups for one `explain_events` call."""

    def __init__(self, connection: Connection, audience: ExplanationAudience) -> None:
        self._c = connection
        self._a = audience
        self._characters: set[uuid.UUID] = set()
        self._parties: set[uuid.UUID] = set()
        self._builds: set[uuid.UUID] = set()
        self._times: set[uuid.UUID] = set()
        self._sessions: set[uuid.UUID] = set()
        self._character_names: dict[uuid.UUID, str] = {}
        self._party_names: dict[uuid.UUID, str] = {}
        self._build_rows: dict[uuid.UUID, tuple[uuid.UUID, str | None]] = {}
        self._time_text: dict[uuid.UUID, str] = {}
        self._session_rows: dict[uuid.UUID, ExplanationSession] = {}

    # -- collection -----------------------------------------------------------------------
    def want_event_effects(
        self, family: str, effects: list[Any], participants: list[uuid.UUID]
    ) -> None:
        if family in (FAMILY_PARTY_JOINED, FAMILY_PARTY_LEFT, FAMILY_BUILD):
            subject = _subject_id(effects, participants)
            if subject is not None:
                self._characters.add(subject)
        for eff in effects:
            previous, new = _as_uuid(eff.previous_value), _as_uuid(eff.new_value)
            if family in (FAMILY_PARTY_JOINED, FAMILY_PARTY_LEFT):
                self._parties.update(i for i in (previous, new) if i is not None)
            elif family == FAMILY_BUILD:
                self._builds.update(i for i in (previous, new) if i is not None)
            elif family in (FAMILY_CLOCK_ADVANCED, FAMILY_CLOCK_CORRECTED):
                self._times.update(i for i in (previous, new) if i is not None)

    def prefetch(self) -> None:
        self._characters_prefetch()
        if self._parties:
            self._party_names = {
                r.party_id: str(r.name)
                for r in self._c.execute(
                    text("""
                        SELECT p.party_id, p.name
                        FROM campaign.parties p
                        JOIN campaign.campaign_parties cp ON cp.party_id = p.party_id
                        JOIN core.lifecycle_statuses ls
                          ON ls.lifecycle_status_id = p.lifecycle_status_id
                        WHERE cp.campaign_id = :c AND p.party_id = ANY(CAST(:ids AS uuid[]))
                          AND (CAST(:editor AS boolean) OR ls.code = :active)
                    """),
                    {
                        "c": self._a.campaign_id,
                        "ids": sorted(self._parties),
                        "editor": self._a.can_edit,
                        "active": PARTY_ACTIVE,
                    },
                )
            }
        if self._builds:
            self._build_rows = {
                r.character_build_id: (r.character_id, r.label)
                for r in self._c.execute(
                    text("""
                        SELECT b.character_build_id, b.character_id, b.label
                        FROM character.character_builds b
                        JOIN core.entities ce ON ce.entity_id = b.character_id
                        WHERE b.character_build_id = ANY(CAST(:ids AS uuid[]))
                          AND ce.world_id = :w
                    """),
                    {"ids": sorted(self._builds), "w": self._a.world_id},
                )
            }

    def _characters_prefetch(self) -> None:
        if not self._characters:
            return
        visible = discoverable_entity_ids(
            self._c,
            sorted(self._characters),
            world_id=self._a.world_id,
            timeline_id=self._a.timeline_id,
            visibility=self._a.visibility,
        )
        if visible:
            self._character_names = {
                r.entity_id: str(r.canonical_name)
                for r in self._c.execute(
                    text(
                        "SELECT entity_id, canonical_name FROM core.entities "
                        "WHERE entity_id = ANY(CAST(:ids AS uuid[])) AND world_id = :w"
                    ),
                    {"ids": sorted(visible), "w": self._a.world_id},
                )
            }

    # -- references -----------------------------------------------------------------------
    def character(self, character_id: uuid.UUID | None) -> ExplanationRef:
        if character_id is None or character_id not in self._character_names:
            return _unavailable("character")
        return ExplanationRef(
            NAMED,
            "character",
            character_id,
            self._character_names[character_id],
            self._a.may_open_character(character_id),
        )

    def party(self, party_id: uuid.UUID | None) -> ExplanationRef:
        if party_id is None:
            return _unrecorded("party")
        name = self._party_names.get(party_id)
        if name is None:
            return _unavailable("party")
        return ExplanationRef(NAMED, "party", party_id, name, True)

    def _build(self, build_id: uuid.UUID | None, character_id: uuid.UUID | None) -> ExplanationRef:
        if build_id is None:
            return _unrecorded("build")
        row = self._build_rows.get(build_id)
        if row is None or row[0] != character_id:
            return _unavailable("build")
        return ExplanationRef(NAMED, "build", None, row[1] or "Unlabeled build", False)

    # -- time and session -----------------------------------------------------------------
    def event_time(self, world_time_id: uuid.UUID) -> str:
        return clock_display(self._c, world_time_id)

    def _clock_time(self, value: object) -> ExplanationClockTime:
        if value is None:
            return ExplanationClockTime(UNRECORDED)
        time_id = _as_uuid(value)
        if time_id is None:
            return ExplanationClockTime(UNAVAILABLE)
        if time_id not in self._time_text:
            in_world = self._c.execute(
                text("SELECT 1 FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
                {"t": time_id, "w": self._a.world_id},
            ).scalar()
            if in_world is None:
                return ExplanationClockTime(UNAVAILABLE)
            self._time_text[time_id] = clock_display(self._c, time_id)
        return ExplanationClockTime(NAMED, self._time_text[time_id])

    def session(self, session_id: uuid.UUID | None) -> ExplanationSession | None:
        if session_id is None or not self._a.may_view_session(session_id):
            return None
        if session_id not in self._session_rows:
            row = self._c.execute(
                text("""
                    SELECT session_number, title FROM campaign.sessions
                    WHERE session_id = :s AND campaign_id = :c
                """),
                {"s": session_id, "c": self._a.campaign_id},
            ).one_or_none()
            if row is None:
                return None
            self._session_rows[session_id] = ExplanationSession(
                session_id, int(row.session_number), row.title
            )
        return self._session_rows[session_id]

    # -- families -------------------------------------------------------------------------
    def party_fields(self, effects: list[Any], participants: list[uuid.UUID]) -> dict[str, Any]:
        eff = next((f for f in effects if f.target_component == PARTY_MEMBERSHIP_COMPONENT), None)
        party_id = None
        if eff is not None:
            party_id = _as_uuid(eff.new_value) or _as_uuid(eff.previous_value)
        return {
            "subject": self.character(_subject_id(effects, participants)),
            "party": self.party(party_id) if eff is not None else _unrecorded("party"),
        }

    def build_fields(self, effects: list[Any], participants: list[uuid.UUID]) -> dict[str, Any]:
        character_id = _subject_id(effects, participants)
        subject = self.character(character_id)
        fields: dict[str, Any] = {"subject": subject, "build_detail": BUILD_DETAIL_GENERIC}
        eff = next((f for f in effects if f.target_component == BUILD_COMPONENT), None)
        if (
            eff is None
            or character_id is None
            or subject.state != NAMED
            or not self._a.may_read_build(character_id)
        ):
            return fields
        fields["build_detail"] = BUILD_DETAIL_FULL
        fields["previous_build"] = self._build(_as_uuid(eff.previous_value), character_id)
        fields["new_build"] = self._build(_as_uuid(eff.new_value), character_id)
        return fields

    def clock_fields(self, effects: list[Any]) -> dict[str, Any]:
        eff = next((f for f in effects if f.target_component == "current_world_time_id"), None)
        if eff is None:
            return {}
        return {
            "previous_time": self._clock_time(eff.previous_value),
            "new_time": self._clock_time(eff.new_value),
        }


def _subject_id(effects: list[Any], participants: list[uuid.UUID]) -> uuid.UUID | None:
    for eff in effects:
        if eff.target_entity_id is not None:
            return eff.target_entity_id  # type: ignore[no-any-return]
    return participants[0] if participants else None


def _travel_entries(
    connection: Connection, audience: ExplanationAudience, events: Sequence[Any]
) -> dict[uuid.UUID, SessionTravelEntry]:
    if not events:
        return {}
    entries = list_session_travel(
        connection,
        events=[
            SessionEventView(
                event_id=e.event_id,
                name="",
                summary=None,
                event_type_code=str(e.type_code),
                event_status_code=str(e.status_code),
                world_time_id=e.world_time_id,
                details=None,
                world_time=clock_display(connection, e.world_time_id),
            )
            for e in events
        ],
        world_id=audience.world_id,
        timeline_id=audience.timeline_id,
        visibility=audience.visibility,
        include_gm_note=False,
        any_event_type=True,
    )
    return {entry.event_id: entry for entry in entries}


def _advance_details(
    connection: Connection, advance_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None]]:
    """Origin and member-safe explanation of advances recorded under the CP-9b contract. The
    origin is read from the stored cause rows, not from what the caller may see, so a cause the
    caller cannot open still reads as caused rather than manual."""
    if not advance_ids:
        return {}
    rows = connection.execute(
        text("""
            SELECT d.event_id, d.member_explanation,
                   EXISTS (
                       SELECT 1 FROM narrative.event_causes ec
                       JOIN narrative.events ce ON ce.event_id = ec.cause_event_id
                       JOIN narrative.event_types ct ON ct.event_type_id = ce.event_type_id
                       WHERE ec.event_id = d.event_id AND ct.code <> ALL(CAST(:clock AS text[]))
                   ) AS has_cause
            FROM narrative.clock_advance_details d
            WHERE d.event_id = ANY(CAST(:ids AS uuid[]))
        """),
        {"ids": list(advance_ids), "clock": sorted(_CLOCK_TYPES)},
    )
    return {
        r.event_id: (ORIGIN_EVENT_CAUSE if r.has_cause else ORIGIN_MANUAL, r.member_explanation)
        for r in rows
    }


def _relations(
    connection: Connection, audience: ExplanationAudience, events: Sequence[Any]
) -> dict[uuid.UUID, tuple[ExplanationRelation, ...]]:
    ids = [e.event_id for e in events]
    type_of = {e.event_id: str(e.type_code) for e in events}
    pending: dict[uuid.UUID, list[tuple[str, uuid.UUID, str | None, bool]]] = {i: [] for i in ids}

    for row in connection.execute(
        text("""
            SELECT event_id, cause_event_id FROM narrative.event_causes
            WHERE event_id = ANY(CAST(:ids AS uuid[])) AND cause_event_id IS NOT NULL
            ORDER BY event_cause_id
        """),
        {"ids": ids},
    ):
        pending[row.event_id].append(("cause", row.cause_event_id, None, False))
    for row in connection.execute(
        text("""
            SELECT ec.cause_event_id AS event_id, ec.event_id AS later_event_id
            FROM narrative.event_causes ec
            JOIN narrative.events le ON le.event_id = ec.event_id
            JOIN narrative.event_types lt ON lt.event_type_id = le.event_type_id
            WHERE ec.cause_event_id = ANY(CAST(:ids AS uuid[])) AND lt.code = :corrected
            ORDER BY ec.event_cause_id
        """),
        {"ids": ids, "corrected": CLOCK_EVENT_CORRECTED},
    ):
        if type_of.get(row.event_id) in _CLOCK_TYPES:
            pending[row.event_id].append((REL_CORRECTED_BY_CLOCK, row.later_event_id, None, False))
    for row in connection.execute(
        text("""
            SELECT corrected_event_id, correcting_event_id, replacement_event_id, reason
            FROM narrative.event_corrections
            WHERE corrected_event_id = ANY(CAST(:ids AS uuid[]))
               OR correcting_event_id = ANY(CAST(:ids AS uuid[]))
               OR replacement_event_id = ANY(CAST(:ids AS uuid[]))
        """),
        {"ids": ids},
    ):
        reason = row.reason if audience.can_edit else None
        if row.corrected_event_id in pending:
            pending[row.corrected_event_id].append(
                (REL_CORRECTED_BY, row.correcting_event_id, reason, True)
            )
            if row.replacement_event_id is not None:
                pending[row.corrected_event_id].append(
                    (REL_REPLACED_BY, row.replacement_event_id, None, True)
                )
        if row.correcting_event_id in pending:
            pending[row.correcting_event_id].append(
                (REL_CORRECTS, row.corrected_event_id, reason, True)
            )
        if row.replacement_event_id in pending:
            pending[row.replacement_event_id].append(
                (REL_REPLACES, row.corrected_event_id, None, True)
            )

    related = sorted({target for items in pending.values() for _, target, _, _ in items})
    refs = _event_refs(connection, audience, related)

    out: dict[uuid.UUID, tuple[ExplanationRelation, ...]] = {}
    for event_id, items in pending.items():
        relations: list[ExplanationRelation] = []
        seen: set[tuple[str, uuid.UUID]] = set()
        # A correcting event cites the event it corrects as its cause; the correction link
        # already says so.
        corrected = {target for _, target, _, is_correction in items if is_correction}
        for relation, target, reason, is_correction in items:
            if relation == "cause" and target in corrected:
                continue
            if relation == "cause":
                relation = _cause_relation(type_of[event_id], refs.get(target))
            if (relation, target) in seen:
                continue
            seen.add((relation, target))
            ref = refs.get(target)
            if ref is None:
                if is_correction:
                    relations.append(ExplanationRelation(relation, _unavailable("event"), reason))
                continue
            relations.append(ExplanationRelation(relation, ref[0], reason))
        # Cause rows share a creation instant and have random ids, so order by meaning instead.
        relations.sort(key=lambda r: _RELATION_ORDER.get(r.relation, len(_RELATION_ORDER)))
        out[event_id] = tuple(relations)
    return out


def _cause_relation(type_code: str, ref: tuple[ExplanationRef, str] | None) -> str:
    """The existing chain row of a clock event reads as following the previous clock change (or
    correcting it); it is not proof that the earlier change caused gameplay. Only a clock event's
    own chain row is read this way: any other event whose cause is a clock event, and any other
    cause, is a recorded cause."""
    if type_code in _CLOCK_TYPES and ref is not None and ref[1] in _CLOCK_TYPES:
        return REL_CORRECTS_CLOCK if type_code == CLOCK_EVENT_CORRECTED else REL_FOLLOWS_CLOCK
    return REL_CAUSED_BY


def _event_refs(
    connection: Connection, audience: ExplanationAudience, event_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[ExplanationRef, str]]:
    """Own-timeline events the caller may name (and open), with their type code."""
    if not event_ids:
        return {}
    rows = connection.execute(
        text("""
            SELECT ev.event_id, ce.canonical_name, et.code AS type_code
            FROM narrative.events ev
            JOIN core.entities ce ON ce.entity_id = ev.event_id
            JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
            WHERE ev.event_id = ANY(CAST(:ids AS uuid[]))
              AND ev.timeline_id = :t AND ce.world_id = :w
        """),
        {"ids": list(event_ids), "t": audience.timeline_id, "w": audience.world_id},
    ).all()
    if audience.authoring:
        allowed = {r.event_id for r in rows}
    else:
        allowed = set(
            discoverable_entity_ids(
                connection,
                [r.event_id for r in rows],
                world_id=audience.world_id,
                timeline_id=audience.timeline_id,
                visibility=audience.visibility,
            )
        )
    return {
        r.event_id: (
            ExplanationRef(NAMED, "event", r.event_id, str(r.canonical_name), True),
            str(r.type_code),
        )
        for r in rows
        if r.event_id in allowed
    }
