"""The portable FastAPI application entry point.

Portable by design (ADR 0012, docs/LOCAL_DEPLOYMENT.md): FastAPI runs under
Uvicorn, in a container or otherwise, and talks to PostgreSQL over the
network. This module is intentionally deployment-neutral and does not couple
application behavior to any specific hosting platform.

OIDC bearer-token verification (`dnd_ai.api.auth`/`dnd_ai.domain.tokens`)
is delivered and used by the command endpoints below
(`dnd_ai.api.encounters`, `dnd_ai.api.items`, `dnd_ai.api.quests`,
`dnd_ai.api.relationships`, `dnd_ai.api.events`, `dnd_ai.api.interactions`,
`dnd_ai.api.integration`, `dnd_ai.api.memberships`,
`dnd_ai.api.access_grants`, `dnd_ai.api.access_groups`) and the query
endpoints (`dnd_ai.api.dungeon`, `dnd_ai.api.characters`, `dnd_ai.api.knowledge`,
`dnd_ai.api.summary`, `dnd_ai.api.access_overview`) via
`dnd_ai.api.access`. `dnd_ai.api.campaigns` is the one exception: it has no
campaign yet to resolve `dnd_ai.api.access.require_campaign_capability`
against, so it authenticates the caller directly via `dnd_ai.api.auth.
get_authenticated_user_id` instead — see its own module docstring. This
module remains the plumbing every router builds on: app factory, error
contract, correlation IDs, health/readiness, per-request transaction
management, authentication, and CORS — routers register their own paths,
this module only mounts them.

CORS (`CORSMiddleware` below, `dnd_ai.config.Settings.foundry_allowed_
origins`) exists specifically for the FoundryVTT module: it runs as
browser JavaScript on its own origin, separate from this API's origin in
the documented deployment topology (`docs/LOCAL_DEPLOYMENT.md`), so a real
browser sends an `OPTIONS` preflight before every authenticated request.
No other client of this API is a browser page reading another origin's
response — the React UI is expected to share this API's origin, and the
Discord bot/MCP interface/`scripts/foundry_provision.py` are server-side
or CLI HTTP clients CORS does not apply to at all (a browser-enforced
restriction, not a server-side authorization mechanism) — so the
allowlist is deliberately narrow and never defaults to permitting any
origin.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import Engine, text
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from dnd_ai.config import PRODUCTION_REQUIRED_DATABASE_ROLE, foundry_allowed_origins_tuple, settings

from .access_grants import router as access_grants_router
from .access_groups import router as access_groups_router
from .access_overview import router as access_overview_router
from .ai_npc import router as ai_npc_router
from .ai_synthesis import router as ai_synthesis_router
from .audit_history import router as audit_history_router
from .auth import dispose_jwks_client
from .cache_control import NoStoreMiddleware
from .campaign_clock import router as campaign_clock_router
from .campaign_invitations import router as campaign_invitations_router
from .campaigns import router as campaigns_router
from .character_builds import router as character_builds_router
from .character_state import router as character_state_router
from .characters import router as characters_router
from .correlation import CorrelationIdMiddleware
from .deps import dispose_engine, get_engine, verify_database_identity
from .dungeon import router as dungeon_router
from .dungeon_authoring import router as dungeon_authoring_router
from .encounter_preparation import router as encounter_preparation_router
from .encounters import router as encounters_router
from .entity_lifecycle import router as entity_lifecycle_router
from .errors import install_error_handlers
from .event_corrections import router as event_corrections_router
from .events import router as events_router
from .foundry_pairing import router as foundry_pairing_router
from .integration import router as integration_router
from .interactions import router as interactions_router
from .invitation_onboarding import router as invitation_onboarding_router
from .item_authoring import router as item_authoring_router
from .item_definition_authoring import router as item_definition_authoring_router
from .items import router as items_router
from .knowledge import router as knowledge_router
from .knowledge_authoring import router as knowledge_authoring_router
from .knowledge_runtime import router as knowledge_runtime_router
from .local_auth import router as local_auth_router
from .location_authoring import router as location_authoring_router
from .memberships import router as memberships_router
from .movement import router as movement_router
from .npc_authoring import router as npc_authoring_router
from .npc_portrayal import router as npc_portrayal_router
from .organization_authoring import router as organization_authoring_router
from .organization_members import router as organization_members_router
from .parties import router as parties_router
from .player_character_authoring import router as player_character_authoring_router
from .preview import router as preview_router
from .quest_authoring import router as quest_authoring_router
from .quest_runtime import router as quest_runtime_router
from .quests import router as quests_router
from .reference_corpus import router as reference_corpus_router
from .relationship_authoring import router as relationship_authoring_router
from .relationships import router as relationships_router
from .review_queue import router as review_queue_router
from .rulesets import router as rulesets_router
from .session_authoring import router as session_authoring_router
from .session_play import router as session_play_router
from .sessions import router as sessions_router
from .sources import router as sources_router
from .summary import router as summary_router
from .timelines import router as timelines_router
from .travel import router as travel_router
from .user_preferences import router as user_preferences_router
from .world_canon import router as world_canon_router
from .world_explorer import router as world_explorer_router
from .world_sharing import router as world_sharing_router
from .world_time import router as world_time_router
from .worlds import router as worlds_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """`dnd_ai.config.Settings` already refuses to start if
    `DND_AI_DATABASE_URL` doesn't *name* `app_read_write` (production
    only) — but a URL string is only a claim about identity, not proof of
    it. In production, this eagerly opens the engine and confirms a real
    connection actually authenticates as `app_read_write`
    (`verify_database_identity` — checks `session_user`/`current_user`,
    catching a connection pooler or an implicit/explicit `SET ROLE` that
    the static check can't see) before the application ever finishes
    starting. Deliberately here, not deferred to `/readyz`: a startup
    failure in a FastAPI/Starlette lifespan aborts Uvicorn's own startup
    entirely, so the process never binds its port and `/healthz` can never
    be reached at all — strictly stronger than a 503 from `/readyz`, which
    still requires the process to be up and answering. Outside production
    this check never runs, since local/test intentionally connect as the
    `postgres` admin credential."""
    if settings.environment == "production":
        engine = get_engine()
        try:
            verify_database_identity(engine, expected_role=PRODUCTION_REQUIRED_DATABASE_ROLE)
        except Exception:
            dispose_engine()
            raise
    try:
        yield
    finally:
        dispose_engine()
        dispose_jwks_client()


def create_app() -> FastAPI:
    app = FastAPI(title="D&D AI World Platform API", lifespan=_lifespan)
    # Outermost middleware (added first — Starlette applies user middleware
    # in the order added, from outside in), so a browser's CORS preflight
    # is answered, and CORS headers are attached to every response
    # including errors, before anything else in the stack runs.
    # `dnd_ai.config.settings.foundry_allowed_origins` is the only source
    # of truth for the allowlist (no wildcard, ever — see that module's
    # own docstring); an empty allowlist is a safe default that permits no
    # cross-origin browser access rather than widening to "allow anything."
    # `allow_credentials=False`: the FoundryVTT module authenticates with
    # an `Authorization` header, never a cookie, so there is no reason to
    # enable credentialed CORS requests here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(foundry_allowed_origins_tuple(settings)),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Foundry-Actor-Id", "Idempotency-Key"],
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(NoStoreMiddleware)
    install_error_handlers(app)
    app.include_router(access_grants_router)
    app.include_router(access_groups_router)
    app.include_router(access_overview_router)
    app.include_router(ai_npc_router)
    app.include_router(ai_synthesis_router)
    app.include_router(audit_history_router)
    app.include_router(campaign_invitations_router)
    app.include_router(campaign_clock_router)
    app.include_router(campaigns_router)
    app.include_router(character_builds_router)
    app.include_router(character_state_router)
    app.include_router(characters_router)
    app.include_router(dungeon_router)
    app.include_router(encounter_preparation_router)
    app.include_router(review_queue_router)
    app.include_router(sources_router)
    app.include_router(encounters_router)
    app.include_router(entity_lifecycle_router)
    app.include_router(events_router)
    app.include_router(event_corrections_router)
    app.include_router(foundry_pairing_router)
    app.include_router(integration_router)
    app.include_router(interactions_router)
    app.include_router(invitation_onboarding_router)
    app.include_router(items_router)
    app.include_router(knowledge_router)
    app.include_router(local_auth_router)
    app.include_router(location_authoring_router)
    app.include_router(memberships_router)
    app.include_router(movement_router)
    app.include_router(npc_authoring_router)
    app.include_router(parties_router)
    app.include_router(player_character_authoring_router)
    app.include_router(knowledge_authoring_router)
    app.include_router(organization_authoring_router)
    app.include_router(preview_router)
    app.include_router(quest_authoring_router)
    app.include_router(quests_router)
    app.include_router(reference_corpus_router)
    app.include_router(relationships_router)
    app.include_router(rulesets_router)
    app.include_router(sessions_router)
    app.include_router(session_authoring_router)
    app.include_router(session_play_router)
    app.include_router(quest_runtime_router)
    app.include_router(knowledge_runtime_router)
    app.include_router(dungeon_authoring_router)
    app.include_router(relationship_authoring_router)
    app.include_router(organization_members_router)
    app.include_router(travel_router)
    app.include_router(item_authoring_router)
    app.include_router(item_definition_authoring_router)
    app.include_router(npc_portrayal_router)
    app.include_router(summary_router)
    app.include_router(timelines_router)
    app.include_router(user_preferences_router)
    app.include_router(world_explorer_router)
    app.include_router(world_canon_router)
    app.include_router(world_sharing_router)
    app.include_router(world_time_router)
    app.include_router(worlds_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Cheap process-liveness only — no database, no I/O. This is what
        a container orchestrator restarts the process over if it stops
        answering; it must never itself depend on PostgreSQL being up, or a
        database outage would also make the process look dead rather than
        just not-yet-ready (docs/LOCAL_DEPLOYMENT.md "Operations")."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(engine: Annotated[Engine, Depends(get_engine)]) -> JSONResponse:
        """Whether this instance can actually serve traffic: required
        configuration loaded (implicitly true by the time this runs —
        `dnd_ai.config.Settings()` fails process startup outright otherwise,
        see that module) and a minimal PostgreSQL round trip through the
        same engine/connection wiring every other endpoint uses — not a
        parallel, unrepresentative connection. Suitable for a Docker Compose
        `healthcheck:` hitting this over the private network
        (docs/LOCAL_DEPLOYMENT.md "Compose responsibilities and network
        policy") — never needs its own PostgreSQL or Uvicorn port exposed.
        Failure returns 503 and a fixed, non-secret body. The underlying
        exception is never logged as `str(exc)` or with its traceback
        (`exc_info=True`) — a driver connection failure routinely embeds
        the DSN, host, database name, or username in its message, and
        SQLAlchemy/psycopg exceptions are not guaranteed to keep a
        password out of that text either. Only the exception's class name
        (e.g. `OperationalError`) is logged — enough to distinguish
        "database unreachable" from "some other bug in this handler"
        operationally, without risking a secret in the log stream."""
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning(
                "readiness check failed: database round trip did not succeed (%s)",
                type(exc).__name__,
            )
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    return app


app = create_app()
