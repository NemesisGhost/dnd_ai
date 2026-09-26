export interface PendingCampaignInvitation {
    campaign_invitation_id: string
    invited_email: string | null
    invited_by_display_name: string
    created_at: string
    expires_at: string
}

export interface PendingCampaignInvitationList {
    invitations: PendingCampaignInvitation[]
}

export interface CreateCampaignInvitationResponse {
    campaign_invitation_id: string
    token: string | null
}

export interface RevokeCampaignInvitationResponse {
    campaign_invitation_id: string
}

export interface AcceptCampaignInvitationResponse {
    campaign_id: string
    campaign_membership_id: string
}