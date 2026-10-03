import type {
    BeginInvitationOnboardingResponse,
    CompleteInvitationOnboardingResponse,
    InvitationOnboardingStatus,
    RegisterInvitedAccountResponse,
} from "../types/invitationOnboarding"

export class InvitationOnboardingRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "InvitationOnboardingRequestError"
        this.status = status
    }
}

// The raw invitation token is a function argument only, never stored in
// any client-side state by this module -- see
// PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §6.2's "Token elimination."
export async function beginInvitationOnboarding(
    invitationToken: string,
    signal?: AbortSignal,
): Promise<BeginInvitationOnboardingResponse> {
    const response = await fetch("/api/campaign-invitations/onboarding/start", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ token: invitationToken }),
    })

    if (!response.ok) {
        throw new InvitationOnboardingRequestError(
            response.status,
            `Begin invitation onboarding request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as BeginInvitationOnboardingResponse
}

export async function fetchInvitationOnboardingStatus(
    signal?: AbortSignal,
): Promise<InvitationOnboardingStatus> {
    const response = await fetch("/api/campaign-invitations/onboarding/status", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
        },
    })

    if (!response.ok) {
        throw new InvitationOnboardingRequestError(
            response.status,
            `Invitation onboarding status request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as InvitationOnboardingStatus
}

export async function registerInvitedAccount(
    loginName: string,
    displayName: string,
    password: string,
    onboardingCsrfToken: string,
    signal?: AbortSignal,
): Promise<RegisterInvitedAccountResponse> {
    const response = await fetch("/api/campaign-invitations/onboarding/register", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-Onboarding-CSRF-Token": onboardingCsrfToken,
        },
        body: JSON.stringify({
            login_name: loginName,
            display_name: displayName,
            password,
        }),
    })

    if (!response.ok) {
        throw new InvitationOnboardingRequestError(
            response.status,
            `Register invited account request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as RegisterInvitedAccountResponse
}

export async function completeInvitationOnboarding(
    csrfToken: string,
    signal?: AbortSignal,
): Promise<CompleteInvitationOnboardingResponse> {
    const response = await fetch("/api/campaign-invitations/onboarding/complete", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "X-CSRF-Token": csrfToken,
        },
    })

    if (!response.ok) {
        throw new InvitationOnboardingRequestError(
            response.status,
            `Complete invitation onboarding request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as CompleteInvitationOnboardingResponse
}

export async function cancelInvitationOnboarding(
    onboardingCsrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    const response = await fetch("/api/campaign-invitations/onboarding/cancel", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            "X-Onboarding-CSRF-Token": onboardingCsrfToken,
        },
    })

    if (!response.ok) {
        throw new InvitationOnboardingRequestError(
            response.status,
            `Cancel invitation onboarding request failed with status ${response.status}`,
        )
    }
}
