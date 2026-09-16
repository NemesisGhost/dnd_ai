export class LogoutRequestError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`Logout request failed with status ${status}`)
    this.name = "LogoutRequestError"
    this.status = status
  }
}

export async function logout(
  csrfToken: string,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/auth/logout", {
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
    throw new LogoutRequestError(response.status)
  }
}
