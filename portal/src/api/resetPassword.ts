export class ResetPasswordRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "ResetPasswordRequestError"
        this.status = status
    }
}

export interface ResetPasswordResponse {
    user_id: string
    sessions_revoked: boolean
}

// `token` and `newPassword` are plain function arguments only, never
// retained by this module.
export async function resetPassword(
    token: string,
    newPassword: string,
    signal?: AbortSignal,
): Promise<ResetPasswordResponse> {
    const response = await fetch("/api/auth/password-reset", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ token, new_password: newPassword }),
    })

    if (!response.ok) {
        throw new ResetPasswordRequestError(
            response.status,
            `Reset password request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as ResetPasswordResponse
}
