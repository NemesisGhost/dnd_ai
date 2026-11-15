"""R01: the routes that open a keyed pre-write plan (plan section 6.25).

A route listed here is in `R01_FINALIZED_ROUTES` and, unlike the post-write routes of S2-S4b, opens its
plan in `PlanMode.PRE_WRITE` with the declarations its handler chooses from by the reservation's server
outcome (`ReservationDeclarations`). Every lock of the request is taken before `plan.finalize`, every write
is a declared `plan.execute` step after it, and the reservation's campaign foreign key is deferred.

The set grows only with a reviewed slice (S5-D: the two invitation routes; S5-E1: the three campaign
lifecycle routes; S5-E2: add member and the four role operations; S5-E3 onward: the rest).

`R01_UNKEYED_PRE_WRITE_ROUTES` (S5-E2 ownership-transfer amendment, T4) is the registry of routes that open a
pre-write plan with **one** declaration and no reservation: they are not idempotent, an `Idempotency-Key`
header is ignored, and they have no receipt step. It is disjoint from the keyed registry and holds finalized
routes only (`begin_route_plan` refuses a route that is in both, or is not finalized).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from dnd_ai.commands.campaign_invitation_plans import CREATE_DECLARATIONS, REVOKE_DECLARATIONS
from dnd_ai.commands.campaign_lifecycle_plans import (
    ARCHIVE_DECLARATIONS,
    REACTIVATE_DECLARATIONS,
    UPDATE_DECLARATIONS,
)
from dnd_ai.commands.membership_role_plans import (
    ADD_DECLARATIONS,
    ASSIGN_DECLARATIONS,
    CHANGE_DECLARATIONS,
    TRANSFER_DECLARATION,
)
from dnd_ai.commands.membership_role_plans import (
    REVOKE_DECLARATIONS as REVOKE_ROLE_DECLARATIONS,
)
from dnd_ai.domain.authorization import ReservationDeclarations
from dnd_ai.domain.authorization_steps import PreWriteDeclaration

R01_KEYED_PRE_WRITE_ROUTES: Final[Mapping[tuple[str, str], ReservationDeclarations]] = (
    MappingProxyType(
        {
            ("POST", "/campaigns/{campaign_id}/invitations"): CREATE_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/invitations/{campaign_invitation_id}/revoke",
            ): REVOKE_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/update"): UPDATE_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/archive"): ARCHIVE_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/reactivate"): REACTIVATE_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/memberships"): ADD_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/roles",
            ): ASSIGN_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change",
            ): CHANGE_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke",
            ): REVOKE_ROLE_DECLARATIONS,
        }
    )
)

R01_UNKEYED_PRE_WRITE_ROUTES: Final[Mapping[tuple[str, str], PreWriteDeclaration]] = (
    MappingProxyType(
        {("POST", "/campaigns/{campaign_id}/ownership-transfer"): TRANSFER_DECLARATION}
    )
)
