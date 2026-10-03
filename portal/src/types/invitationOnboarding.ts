export type InvitationOnboardingNextAction = "sign_in_or_register" | "confirm"

export interface BeginInvitationOnboardingResponse {
    campaign_display_name: string
    invitation_expires_at: string
    onboarding_expires_at: string
    onboarding_csrf_token: string
    next_action: InvitationOnboardingNextAction
    signed_in_display_name: string | null
}

export interface InvitationOnboardingStatus {
    campaign_display_name: string
    invitation_expires_at: string
    onboarding_expires_at: string
    onboarding_csrf_token: string
    next_action: InvitationOnboardingNextAction
    signed_in_display_name: string | null
}

export interface RegisterInvitedAccountResponse {
    csrf_token: string
    campaign_display_name: string
}

export interface CompleteInvitationOnboardingResponse {
    campaign_display_name: string
}
