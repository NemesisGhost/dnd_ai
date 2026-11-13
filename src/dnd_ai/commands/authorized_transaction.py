"""`authorized_transaction`: the context manager for a direct caller of a protected command outside a
request (tests, wrappers such as `player_characters.create_player_character`, any future worker)
(R01 plan section 6.5, rule 5).

    with authorized_transaction(engine, actor_user_id, campaign_id) as (connection, plan):
        command(connection, ..., plan=plan)

It opens one connection and transaction, binds an `AuthorizationPlan` to them, and on a clean exit
finalizes the plan (unless the body already did) and commits. On any failure, including a refused
commit, it abandons the transaction by T0's rule (`finish_connection_transaction`): the DBAPI
ROLLBACK is verified idle, or the connection is invalidated. Forgetting the context manager still
fails closed: a bound plan that is never finalized makes the commit guard refuse.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine

from dnd_ai.api.deps import finish_connection_transaction
from dnd_ai.domain.authorization import (
    AuthorizationPlan,
    PlanMode,
    install_authorization_guard,
)
from dnd_ai.domain.authorization_steps import PreWriteDeclaration


@contextmanager
def authorized_transaction(
    engine: Engine,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    mode: PlanMode = PlanMode.POST_WRITE,
    pre_write: PreWriteDeclaration | None = None,
) -> Iterator[tuple[Connection, AuthorizationPlan]]:
    install_authorization_guard(engine)
    connection = engine.connect()
    try:
        connection.begin()
        plan = AuthorizationPlan.begin(
            connection,
            actor_user_id=actor_user_id,
            campaign_id=campaign_id,
            mode=mode,
            pre_write=pre_write,
        )
    except BaseException:
        connection.close()
        raise
    try:
        yield connection, plan
        if not plan.finalised:
            plan.finalize(connection)
    except BaseException:
        finish_connection_transaction(connection, commit=False)
        raise
    finish_connection_transaction(connection, commit=True)
