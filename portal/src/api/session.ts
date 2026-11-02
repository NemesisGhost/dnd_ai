import type { SessionBootstrap } from "../types/bootstrap"
import { preferenceWritesSettled } from "./preferenceWrites"

export async function fetchSessionBootstrap(
    signal?: AbortSignal,
): Promise<SessionBootstrap | null> {
    // A saved preference written just before this read (the last-visited
    // campaign) must be visible in it, never replaced by the older value.
    await preferenceWritesSettled()
    if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError")
    }

    const response = await fetch("/auth/session", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal,
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