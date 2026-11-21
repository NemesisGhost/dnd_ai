// Who holds reveal authority in a campaign (GET /campaigns/{id}/reveal-delegations). Exactly the keys the API
// returns. The server derives every value (owner status, GM eligibility, whether a delegation is effective):
// the portal never works them out from role codes or the bootstrap. The reason a delegation was made under is
// stored by the server and never returned, so it has no field here; nor does a delegation or role id.

export interface RevealDelegation {
    granted_at: string
    // null when the granting membership no longer exists.
    granted_by_name: string | null
}

// A member who holds the built-in GM role now. `delegation` is set only when it authorizes them.
export interface RevealDelegationMember {
    campaign_membership_id: string
    display_name: string
    delegation: RevealDelegation | null
}

// An open delegation of someone who no longer holds a live GM role: it gives no authority, and the owner can
// still close it with the same revoke.
export interface LapsedRevealDelegation {
    campaign_membership_id: string
    display_name: string
    granted_at: string
    granted_by_name: string | null
}

export interface RevealDelegationState {
    // Whether the caller is a live campaign owner (may grant and revoke). A custom access manager reads and sees false.
    can_manage: boolean
    members: RevealDelegationMember[]
    lapsed_delegations: LapsedRevealDelegation[]
}
