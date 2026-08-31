import type { SessionBootstrap } from "../types/bootstrap"

export async function fetchSessionBootstrap():
  Promise<SessionBootstrap | null> {
  const response = await fetch("/auth/session", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  })

  if (response.status === 401) {
    return null
  }

  if (!response.ok) {
    throw new Error(
      `Session bootstrap request failed with status ${response.status}`,
    )
  }

  return (await response.json()) as SessionBootstrap
}