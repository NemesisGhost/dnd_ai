"""R01: the routes that open a keyed pre-write plan (plan section 6.25).

A route listed here is in `R01_FINALIZED_ROUTES` and, unlike the post-write routes of S2-S4b, opens its
plan in `PlanMode.PRE_WRITE` with the declarations its handler chooses from by the reservation's server
outcome (`ReservationDeclarations`). Every lock of the request is taken before `plan.finalize`, every write
is a declared `plan.execute` step after it, and the reservation's campaign foreign key is deferred.

The set grows only with a reviewed slice (S5-D: the two invitation routes; S5-E1: the three campaign
lifecycle routes; S5-E2: add member and the four role operations; S5-E3: end membership; S5-E4: resource grants and character relationships; S5-E5: the six access-group routes; S5-E6: the two reveal-delegation routes, unkeyed; S5-F onward: the rest).

`R01_UNKEYED_PRE_WRITE_ROUTES` (S5-E2 ownership-transfer amendment, T4) is the registry of routes that open a
pre-write plan with **one** declaration and no reservation: they are not idempotent, an `Idempotency-Key`
header is ignored, and they have no receipt step. It is disjoint from the keyed registry and holds finalized
routes only (`begin_route_plan` refuses a route that is in both, or is not finalized).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from dnd_ai.commands.access_grant_plans import (
    CHANGE_RELATIONSHIP_DECLARATIONS,
    CREATE_GRANT_DECLARATIONS,
    GRANT_RELATIONSHIP_DECLARATIONS,
    REVOKE_GRANT_DECLARATIONS,
    REVOKE_RELATIONSHIP_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    ADD_DECLARATIONS as ADD_GROUP_MEMBER_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    CREATE_DECLARATIONS as CREATE_GROUP_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    DEACTIVATE_DECLARATIONS as DEACTIVATE_GROUP_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    REACTIVATE_DECLARATIONS as REACTIVATE_GROUP_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    REMOVE_DECLARATIONS as REMOVE_GROUP_MEMBER_DECLARATIONS,
)
from dnd_ai.commands.access_group_plans import (
    UPDATE_DECLARATIONS as UPDATE_GROUP_DECLARATIONS,
)
from dnd_ai.commands.campaign_invitation_plans import CREATE_DECLARATIONS, REVOKE_DECLARATIONS
from dnd_ai.commands.campaign_lifecycle_plans import (
    ARCHIVE_DECLARATIONS,
    REACTIVATE_DECLARATIONS,
    UPDATE_DECLARATIONS,
)
from dnd_ai.commands.membership_end_plans import END_DECLARATIONS
from dnd_ai.commands.membership_role_plans import (
    ADD_DECLARATIONS,
    ASSIGN_DECLARATIONS,
    CHANGE_DECLARATIONS,
    TRANSFER_DECLARATION,
)
from dnd_ai.commands.membership_role_plans import (
    REVOKE_DECLARATIONS as REVOKE_ROLE_DECLARATIONS,
)
from dnd_ai.commands.reveal_delegation_plans import (
    GRANT_DECLARATION as GRANT_REVEAL_DELEGATION_DECLARATION,
)
from dnd_ai.commands.reveal_delegation_plans import (
    REVOKE_DECLARATION as REVOKE_REVEAL_DELEGATION_DECLARATION,
)
from dnd_ai.domain.authorization import ReservationDeclarations
from dnd_ai.domain.authorization_steps import PreWriteDeclaration

#: Finalized post-write routes that may opt in to the reservation deferral (R01 O-1, AM-1.1): their plan is
#: opened as a keyed post-write plan. **Empty in O-1: no production route adopts the capability.** A route
#: listed here must be finalized and in neither pre-write registry (`begin_route_plan` refuses it otherwise).
R01_DEFERRED_RESERVATION_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset()

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
            (
                "POST",
                "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/end",
            ): END_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/memberships/{campaign_membership_id}/character-relationships",
            ): GRANT_RELATIONSHIP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/change",
            ): CHANGE_RELATIONSHIP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/revoke",
            ): REVOKE_RELATIONSHIP_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/resource-grants"): CREATE_GRANT_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/resource-grants/{resource_grant_id}/revoke",
            ): REVOKE_GRANT_DECLARATIONS,
            ("POST", "/campaigns/{campaign_id}/access-groups"): CREATE_GROUP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/access-groups/{access_group_id}/update",
            ): UPDATE_GROUP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/access-groups/{access_group_id}/deactivate",
            ): DEACTIVATE_GROUP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/access-groups/{access_group_id}/reactivate",
            ): REACTIVATE_GROUP_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/access-groups/{access_group_id}/members",
            ): ADD_GROUP_MEMBER_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/access-group-memberships/{access_group_membership_id}/remove",
            ): REMOVE_GROUP_MEMBER_DECLARATIONS,
        }
    )
)

R01_UNKEYED_PRE_WRITE_ROUTES: Final[Mapping[tuple[str, str], PreWriteDeclaration]] = (
    MappingProxyType(
        {
            ("POST", "/campaigns/{campaign_id}/ownership-transfer"): TRANSFER_DECLARATION,
            (
                "POST",
                "/campaigns/{campaign_id}/reveal-delegations",
            ): GRANT_REVEAL_DELEGATION_DECLARATION,
            (
                "POST",
                "/campaigns/{campaign_id}/reveal-delegations/{grantee_campaign_membership_id}/revoke",
            ): REVOKE_REVEAL_DELEGATION_DECLARATION,
        }
    )
)
