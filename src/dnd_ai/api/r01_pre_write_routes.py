"""R01: the routes that open a keyed pre-write plan (plan section 6.25).

A route listed here is in `R01_FINALIZED_ROUTES` and, unlike the post-write routes of S2-S4b, opens its
plan in `PlanMode.PRE_WRITE` with the declarations its handler chooses from by the reservation's server
outcome (`ReservationDeclarations`). Every lock of the request is taken before `plan.finalize`, every write
is a declared `plan.execute` step after it, and the reservation's campaign foreign key is deferred.

The set grows only with a reviewed slice (S5-D: the two invitation routes; S5-E: the rest).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from dnd_ai.commands.campaign_invitation_plans import CREATE_DECLARATIONS, REVOKE_DECLARATIONS
from dnd_ai.domain.authorization import ReservationDeclarations

R01_KEYED_PRE_WRITE_ROUTES: Final[Mapping[tuple[str, str], ReservationDeclarations]] = (
    MappingProxyType(
        {
            ("POST", "/campaigns/{campaign_id}/invitations"): CREATE_DECLARATIONS,
            (
                "POST",
                "/campaigns/{campaign_id}/invitations/{campaign_invitation_id}/revoke",
            ): REVOKE_DECLARATIONS,
        }
    )
)
