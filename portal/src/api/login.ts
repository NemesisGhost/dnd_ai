export interface LoginCredentials {
  login_name: string
  password: string
}

export interface LoginResult {
  user_id: string
  csrf_token: string
}

export class LoginRequestError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`Login request failed with status ${status}`)
    this.name = "LoginRequestError"
    this.status = status
  }
}

export async function login(
  credentials: LoginCredentials,
  signal?: AbortSignal,
): Promise<LoginResult> {
  const response = await fetch("/auth/login", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(credentials),
  })

  if (!response.ok) {
    throw new LoginRequestError(response.status)
  }

  return (await response.json()) as LoginResult
}