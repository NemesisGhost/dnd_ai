export class ActivateAccountRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "ActivateAccountRequestError"
        this.status = status
    }
}

export interface ActivateAccountResponse {
    user_id: string
    login_name: string
}

// `token` and `password` are plain function arguments only, never
// retained by this module -- see the calling page's own docstring for
// the fragment-read discipline that keeps the raw token out of any
// longer-lived state.
export async function activateAccount(
    token: string,
    password: string,
    signal?: AbortSignal,
): Promise<ActivateAccountResponse> {
    const response = await fetch("/api/auth/activate", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ token, password }),
    })

    if (!response.ok) {
        throw new ActivateAccountRequestError(
            response.status,
            `Activate account request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as ActivateAccountResponse
}
