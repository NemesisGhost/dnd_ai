import type { PortalIdentity } from "../auth/auth";

export interface ApiErrorBody {
  error_code?: string;
  message?: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export function createApiClient(getIdentity: () => PortalIdentity | null) {
  return async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const identity = getIdentity();
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (identity?.accessToken) headers.set("Authorization", `Bearer ${identity.accessToken}`);

    const response = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
      throw new ApiError(
        response.status,
        body.error_code ?? "request_failed",
        body.message ?? "The request could not be completed.",
      );
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  };
}
