export class ChangePasswordRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "ChangePasswordRequestError"
        this.status = status
    }
}

// currentPassword/newPassword are plain function arguments, held by the
// caller only for the life of the form and cleared on submit, success,
// and unmount -- never in any storage, never in a URL.
export async function changePassword(
    currentPassword: string,
    newPassword: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    const response = await fetch("/api/auth/change-password", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
        }),
    })

    if (!response.ok) {
        throw new ChangePasswordRequestError(
            response.status,
            `Change password request failed with status ${response.status}`,
        )
    }
}
