"""Deliberate, opt-in live-provider smoke test for Phase 12's AI stack
(docs/PLAN.md Phase 12, §24.0 "real-provider testing is limited to
deliberate smoke verification").

Every other automated test in this repository (`tests/unit`, `tests/database`,
`tests/scenario`) uses `dnd_ai.domain.ai_provider.FakeAiProvider` or a mocked
HTTP transport (`tests/unit/test_ai_provider.py`) — never a live network call.
This script is the one place that calls a real `OpenAiCompatibleProvider`
endpoint, so it is deliberately kept OUT of pytest collection (it lives under
`scripts/`, not `tests/`, and pytest's own `testpaths` never looks there) and
requires an explicit human decision to run at all.

What it does, against a REAL local/self-hosted PostgreSQL database
(`DND_AI_DATABASE_URL`/`DATABASE_URL`, the same settings mechanism every other
command in this codebase uses) and a REAL AI endpoint (`DND_AI_AI_PROVIDER_
BASE_URL`/`_MODEL`/`_API_KEY`, read from `dnd_ai.config.settings` — the exact
production configuration mechanism, never a bespoke CLI flag):

1. Creates a small, entirely fictional, disposable fixture (a throwaway world,
   timeline, campaign, NPC, player character, and party — no real campaign
   data, ever).
2. Calls `dnd_ai.commands.ai_npc.request_npc_conversation_turn` once — a real
   NPC-conversation turn, exercising the provider's function-calling path.
3. Calls `dnd_ai.commands.ai_synthesis.request_campaign_synthesis` once
   (`gm_brief` tier) — exercising the audience-aware synthesis path.
4. Reads back the `ai.context_requests`/`.context_snapshots`/
   `.generated_outputs` rows each call produced, and prints a summary
   confirming they exist and confirming the request/context/output audit
   trail actually recorded something for a real call — never the API key or
   any bearer header, only ids, timings, and truncated response text.
5. Confirms canonical state was not mutated by the AI output alone: this
   fixture has no revealable knowledge or advanceable objective, so neither
   call can produce an `ai.proposed_changes` row — the script asserts exactly
   that (count == 0) rather than merely asserting nothing crashed.
6. Deletes every row it created, in a `finally` block, regardless of outcome
   — this script must never leave disposable smoke-test data behind.

Usage:
    uv run python scripts/ai_provider_smoke_test.py --confirm-live-call

Refuses to run without --confirm-live-call — this is the explicit opt-in the
"never runs accidentally" requirement asks for. Every invocation prints a
warning before making any network call: hitting the real, hosted OpenAI
default (DND_AI_AI_PROVIDER_BASE_URL unset) is a BILLABLE external API call,
charged to whatever account DND_AI_AI_PROVIDER_API_KEY belongs to; pointing
DND_AI_AI_PROVIDER_BASE_URL at an operator's own locally hosted model server
avoids that cost entirely.

Credential handling: there is no --api-key flag, on purpose — the credential
comes only from DND_AI_AI_PROVIDER_API_KEY (a real environment variable, or
the mounted-secret file `${DND_AI_SECRETS_DIR}/dnd_ai_ai_provider_api_key`;
see dnd_ai.config's own module docstring and .env.example's "AI provider"
section) so it can never appear in shell history or a process listing. This
script never prints, logs, or otherwise persists the key anywhere; the only
thing printed about it is whether one is configured at all (present/absent).

Requires: DND_AI_DATABASE_URL or DATABASE_URL pointing at a local/self-hosted
PostgreSQL 18 server (never a production database — see the destructive-
action warning below), and DND_AI_AI_PROVIDER_BASE_URL/_MODEL/_API_KEY
configured for the endpoint you actually want to exercise (see
.env.example's "AI provider" section for both the hosted-OpenAI and
locally-hosted-model paths).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, create_engine, text

from dnd_ai.commands.ai_npc import request_npc_conversation_turn
from dnd_ai.commands.ai_synthesis import request_campaign_synthesis
from dnd_ai.config import settings
from dnd_ai.domain.ai_provider import OpenAiCompatibleProvider

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_RAW_RESPONSE_PREVIEW_CHARS = 200


@dataclass
class _Fixture:
    world_id: uuid.UUID
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID
    ruleset_id: uuid.UUID
    campaign_id: uuid.UUID
    npc_id: uuid.UUID
    pc_id: uuid.UUID
    party_id: uuid.UUID
    npc_agent_id: uuid.UUID
    npc_assignment_id: uuid.UUID
    synthesis_agent_id: uuid.UUID
    synthesis_assignment_id: uuid.UUID


def _lookup_id(connection: Connection, schema: str, table: str, pk: str, code: str) -> uuid.UUID:
    value = connection.execute(
        # schema/table/pk are always one of this module's own fixed call-site
        # literals below, never external input.
        text(f"SELECT {pk} FROM {schema}.{table} WHERE code = :code"),  # noqa: S608
        {"code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID), f"lookup {schema}.{table} code={code!r} not found"
    return value


def _status_id(connection: Connection, table: str, code: str) -> uuid.UUID:
    pk = "canon_status_id" if table == "canon_statuses" else "lifecycle_status_id"
    return _lookup_id(connection, "core", table, pk, code)


def _create_fixture(connection: Connection) -> _Fixture:
    """Builds the smallest fixture that lets both calls run: a throwaway
    world/ruleset/species, one NPC, one player character, one party, one
    pending (never-active, so no access-manager invariant to satisfy)
    campaign, and one agent assignment per use case. Mirrors tests/
    factories.py's own tested shape exactly (make_world/make_timeline/
    make_character/make_party/... — this script cannot import that test-only
    module, so the same schema requirements are reproduced here instead).
    Entirely disposable — every row's name/content below says so."""
    world_id = connection.execute(
        text("""
            INSERT INTO core.worlds (name, slug, lifecycle_status_id)
            VALUES ('AI Provider Smoke Test World', :slug, :status)
            RETURNING world_id
        """),
        {
            "slug": f"ai-smoke-test-{uuid.uuid4().hex[:8]}",
            "status": _status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    timeline_id = connection.execute(
        text("""
            INSERT INTO campaign.timelines (world_id, name, is_primary, lifecycle_status_id)
            VALUES (:world, 'Smoke Test Timeline', true, :status)
            RETURNING timeline_id
        """),
        {"world": world_id, "status": _status_id(connection, "lifecycle_statuses", "active")},
    ).scalar()
    assert isinstance(timeline_id, uuid.UUID)

    world_time_id = connection.execute(
        text("""
            INSERT INTO core.world_times (world_id, world_time_precision_id, year, sort_key)
            VALUES (
                :world,
                (SELECT world_time_precision_id FROM core.world_time_precisions WHERE code = 'exact'),
                1000, 0
            )
            RETURNING world_time_id
        """),
        {"world": world_id},
    ).scalar()
    assert isinstance(world_time_id, uuid.UUID)

    # A throwaway ruleset + current ruleset_version, associated with this
    # world via rules.world_rulesets — required before a character's species
    # or a campaign's ruleset_version_id may reference it (revision 029's
    # same-world-ruleset enforcement).
    ruleset_code = f"smoke_test_ruleset_{uuid.uuid4().hex[:8]}"
    ruleset_id = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": ruleset_code},
    ).scalar()
    assert isinstance(ruleset_id, uuid.UUID)
    ruleset_version_id = connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label, is_current)
            VALUES (:r, 'v1', true)
            RETURNING ruleset_version_id
        """),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(ruleset_version_id, uuid.UUID)
    connection.execute(
        text("INSERT INTO rules.world_rulesets (world_id, ruleset_id) VALUES (:w, :r)"),
        {"w": world_id, "r": ruleset_id},
    )
    species_id = connection.execute(
        text("""
            INSERT INTO rules.species (ruleset_version_id, code, display_name)
            VALUES (:v, 'human', 'Human')
            RETURNING species_id
        """),
        {"v": ruleset_version_id},
    ).scalar()
    assert isinstance(species_id, uuid.UUID)

    campaign_id = connection.execute(
        text("""
            INSERT INTO campaign.campaigns
                (timeline_id, name, lifecycle_status_id, ruleset_version_id)
            VALUES (:timeline, 'AI Provider Smoke Test Campaign', :status, :ruleset_version)
            RETURNING campaign_id
        """),
        {
            "timeline": timeline_id,
            "status": _status_id(connection, "lifecycle_statuses", "pending"),
            "ruleset_version": ruleset_version_id,
        },
    ).scalar()
    assert isinstance(campaign_id, uuid.UUID)

    character_entity_type_id = _lookup_id(
        connection, "core", "entity_types", "entity_type_id", "character"
    )

    def _make_character(name: str) -> uuid.UUID:
        entity_id = connection.execute(
            text("""
                INSERT INTO core.entities
                    (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
                VALUES (:world, :type, :name, :canon, :lifecycle)
                RETURNING entity_id
            """),
            {
                "world": world_id,
                "type": character_entity_type_id,
                "name": name,
                "canon": _status_id(connection, "canon_statuses", "draft"),
                "lifecycle": _status_id(connection, "lifecycle_statuses", "active"),
            },
        ).scalar()
        assert isinstance(entity_id, uuid.UUID)
        connection.execute(
            text("""
                INSERT INTO character.characters (character_id, species_id, size_category)
                VALUES (:c, :s, 'medium')
            """),
            {"c": entity_id, "s": species_id},
        )
        return entity_id

    npc_id = _make_character("Smoke Test Innkeeper")
    pc_id = _make_character("Smoke Test Hero")

    party_id = connection.execute(
        text("""
            INSERT INTO campaign.parties (world_id, name)
            VALUES (:world, 'Smoke Test Party')
            RETURNING party_id
        """),
        {"world": world_id},
    ).scalar()
    assert isinstance(party_id, uuid.UUID)
    connection.execute(
        text(
            "INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:campaign, :party)"
        ),
        {"campaign": campaign_id, "party": party_id},
    )
    connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
            VALUES (:timeline, :party, :member, :world_time)
        """),
        {"timeline": timeline_id, "party": party_id, "member": pc_id, "world_time": world_time_id},
    )

    npc_role_id = _lookup_id(connection, "ai", "agent_roles", "agent_role_id", "npc_portrayal")
    npc_agent_id = connection.execute(
        text("""
            INSERT INTO ai.agents (agent_role_id, display_name, provider, model_identifier)
            VALUES (:role, 'Smoke test NPC agent', :provider, :model)
            RETURNING agent_id
        """),
        {"role": npc_role_id, "provider": "openai", "model": settings.ai_provider_model},
    ).scalar()
    assert isinstance(npc_agent_id, uuid.UUID)
    npc_assignment_id = connection.execute(
        text("""
            INSERT INTO ai.agent_assignments (agent_id, campaign_id, entity_id)
            VALUES (:agent, :campaign, :entity)
            RETURNING agent_assignment_id
        """),
        {"agent": npc_agent_id, "campaign": campaign_id, "entity": npc_id},
    ).scalar()
    assert isinstance(npc_assignment_id, uuid.UUID)

    synthesis_role_id = _lookup_id(
        connection, "ai", "agent_roles", "agent_role_id", "session_summarizer"
    )
    synthesis_agent_id = connection.execute(
        text("""
            INSERT INTO ai.agents (agent_role_id, display_name, provider, model_identifier)
            VALUES (:role, 'Smoke test synthesis agent', :provider, :model)
            RETURNING agent_id
        """),
        {"role": synthesis_role_id, "provider": "openai", "model": settings.ai_provider_model},
    ).scalar()
    assert isinstance(synthesis_agent_id, uuid.UUID)
    synthesis_assignment_id = connection.execute(
        text("""
            INSERT INTO ai.agent_assignments (agent_id, campaign_id, entity_id)
            VALUES (:agent, :campaign, NULL)
            RETURNING agent_assignment_id
        """),
        {"agent": synthesis_agent_id, "campaign": campaign_id},
    ).scalar()
    assert isinstance(synthesis_assignment_id, uuid.UUID)

    return _Fixture(
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        ruleset_id=ruleset_id,
        campaign_id=campaign_id,
        npc_id=npc_id,
        pc_id=pc_id,
        party_id=party_id,
        npc_agent_id=npc_agent_id,
        npc_assignment_id=npc_assignment_id,
        synthesis_agent_id=synthesis_agent_id,
        synthesis_assignment_id=synthesis_assignment_id,
    )


def _cleanup_fixture(engine: Engine, fixture: _Fixture) -> None:
    """core.worlds cascades to campaign.timelines -> .campaigns and to
    campaign.parties (world_id) -> .campaign_parties/.party_memberships, so
    deleting entities + the world is sufficient for all of that — the same
    pattern tests/database/test_ai_npc.py's own committed-fixture cleanup
    already established. The throwaway ruleset (and its ruleset_version/
    species/world_rulesets rows) is not world_id-rooted, so it is deleted
    explicitly."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        connection.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        connection.execute(
            text("DELETE FROM rules.rulesets WHERE ruleset_id = :r"), {"r": fixture.ruleset_id}
        )
        connection.execute(
            text("DELETE FROM ai.agents WHERE agent_id IN (:npc, :synthesis)"),
            {"npc": fixture.npc_agent_id, "synthesis": fixture.synthesis_agent_id},
        )


def _generated_output_summary(engine: Engine, generated_output_id: uuid.UUID) -> str:
    """Reads back exactly the non-secret audit fields — never anything that
    could carry the API key (it is never stored anywhere in these rows in
    the first place; this function does not special-case redacting it, it
    simply never selects a column that could contain one)."""
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT provider, model_identifier, finish_reason, latency_ms, error_message,
                       (structured_output IS NOT NULL) AS has_structured_output,
                       left(coalesce(raw_response, ''), :preview_chars) AS raw_preview
                FROM ai.generated_outputs WHERE generated_output_id = :id
            """),
            {"id": generated_output_id, "preview_chars": _RAW_RESPONSE_PREVIEW_CHARS},
        ).one()
    return (
        f"provider={row.provider} model={row.model_identifier} "
        f"finish_reason={row.finish_reason} latency_ms={row.latency_ms} "
        f"structured_output_present={row.has_structured_output} "
        f"error_message={row.error_message!r} "
        f"raw_response_preview={row.raw_preview!r}"
    )


def _count_proposed_changes(engine: Engine, campaign_id: uuid.UUID) -> int:
    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT count(*) FROM ai.proposed_changes WHERE campaign_id = :campaign"),
            {"campaign": campaign_id},
        ).scalar()
    assert isinstance(value, int)
    return value


def _print_warning_banner(*, base_url: str, has_key: bool) -> None:
    print("=" * 78)
    print("AI PROVIDER SMOKE TEST — about to make a REAL network call.")
    if base_url == _DEFAULT_OPENAI_BASE_URL:
        print(f"Target: {base_url} (real, hosted OpenAI) — THIS CALL MAY BE BILLABLE.")
    else:
        print(f"Target: {base_url} (operator-configured, not the hosted OpenAI default).")
    print(f"Credential configured: {'yes' if has_key else 'no'} (value never printed).")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deliberate, opt-in live-provider smoke test for Phase 12's AI stack. "
            "Never runs without --confirm-live-call."
        )
    )
    parser.add_argument(
        "--confirm-live-call",
        action="store_true",
        help="Required. Confirms you intend to make a real, possibly billable network call.",
    )
    parser.add_argument(
        "--base-url",
        default=settings.ai_provider_base_url,
        help="Override DND_AI_AI_PROVIDER_BASE_URL for this run only (default: configured value).",
    )
    parser.add_argument(
        "--model",
        default=settings.ai_provider_model,
        help="Override DND_AI_AI_PROVIDER_MODEL for this run only (default: configured value).",
    )
    args = parser.parse_args()

    if not args.confirm_live_call:
        print(
            "Refusing to run without --confirm-live-call — this script makes a real, "
            "possibly billable network call and writes/deletes disposable rows in the "
            "database DND_AI_DATABASE_URL/DATABASE_URL currently points at.",
            file=sys.stderr,
        )
        return 2

    assert settings.database_url is not None
    _print_warning_banner(base_url=args.base_url, has_key=settings.ai_provider_api_key is not None)

    engine = create_engine(settings.database_url)
    provider = OpenAiCompatibleProvider(
        api_key=settings.ai_provider_api_key,
        model_identifier=args.model,
        base_url=args.base_url,
    )

    with engine.begin() as connection:
        fixture = _create_fixture(connection)

    try:
        print("\n--- NPC conversation turn ---")
        npc_result = request_npc_conversation_turn(
            engine,
            agent_assignment_id=fixture.npc_assignment_id,
            requesting_user_id=None,
            requesting_character_id=fixture.pc_id,
            requesting_party_id=fixture.party_id,
            player_message="Good evening! What's new around here?",
            provider=provider,
            timeline_id=fixture.timeline_id,
            expected_world_id=fixture.world_id,
            world_time_id=fixture.world_time_id,
        )
        print(f"context_request_id={npc_result.context_request_id}")
        print(f"generated_output_id={npc_result.generated_output_id}")
        print(f"dialogue={npc_result.dialogue!r}")
        print(f"error_message={npc_result.error_message!r}")
        print(f"ai_proposed_change_id={npc_result.ai_proposed_change_id}")
        print(_generated_output_summary(engine, npc_result.generated_output_id))
        npc_ok = npc_result.error_message is None and npc_result.dialogue is not None

        print("\n--- Campaign synthesis (gm_brief) ---")
        synthesis_result = request_campaign_synthesis(
            engine,
            agent_assignment_id=fixture.synthesis_assignment_id,
            campaign_id=fixture.campaign_id,
            audience_tier="gm_brief",
            requesting_user_id=None,
            question_text="What should the GM know right now?",
            provider=provider,
            timeline_id=fixture.timeline_id,
        )
        print(f"context_request_id={synthesis_result.context_request_id}")
        print(f"generated_output_id={synthesis_result.generated_output_id}")
        print(f"answer={synthesis_result.answer!r}")
        print(f"error_message={synthesis_result.error_message!r}")
        print(_generated_output_summary(engine, synthesis_result.generated_output_id))
        synthesis_ok = (
            synthesis_result.error_message is None and synthesis_result.answer is not None
        )

        proposed_change_count = _count_proposed_changes(engine, fixture.campaign_id)
        print(
            f"\nai.proposed_changes rows for this smoke-test campaign: "
            f"{proposed_change_count} (must be 0 — this fixture has no revealable "
            f"knowledge or advanceable objective, so AI output alone could not have "
            f"created one)"
        )
        no_mutation_ok = proposed_change_count == 0

        print("\n--- Result ---")
        print(f"NPC conversation call succeeded: {npc_ok}")
        print(f"Synthesis call succeeded: {synthesis_ok}")
        print(f"No canonical mutation from AI output alone: {no_mutation_ok}")
        return 0 if (npc_ok and synthesis_ok and no_mutation_ok) else 1
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()
        print("\nDisposable smoke-test fixture cleaned up.")


if __name__ == "__main__":
    raise SystemExit(main())
