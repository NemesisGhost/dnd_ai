import { describe, expect, it } from "vitest"
import { ApiRequestError } from "../api/http"
import { classifyApiError } from "./apiError"

const classify = (status: number, code: string | null = null) =>
    classifyApiError(new ApiRequestError(status, code, "corr"))

describe("classifyApiError", () => {
    it.each([
        [0, null, "network"],
        [401, null, "expired"],
        [403, "forbidden", "denied"],
        [404, "not_found", "unavailable"],
        [409, "stale_write", "stale"],
        [409, "conflict", "conflict"],
        [409, "world_archived", "conflict"],
        [409, null, "conflict"],
        [400, "ruleset_not_available", "invalid"],
        [422, "invalid_request", "invalid"],
        [500, "internal_error", "server"],
        [503, null, "server"],
        [418, null, "server"],
    ])("maps %i %s to %s", (status, code, kind) => {
        expect(classify(status, code).kind).toBe(kind)
    })

    it("keeps the code and correlation id", () => {
        expect(classify(409, "stale_write")).toEqual({
            kind: "stale",
            status: 409,
            code: "stale_write",
            correlationId: "corr",
        })
    })

    it("treats an unknown thrown value as a network failure", () => {
        expect(classifyApiError(new Error("boom")).kind).toBe("network")
    })
})
