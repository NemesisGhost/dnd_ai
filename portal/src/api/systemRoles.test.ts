import { afterEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "./platformAccounts"
import { assignSystemRole, revokeSystemRole } from "./systemRoles"

afterEach(() => {
    vi.unstubAllGlobals()
})

function stub(make: () => Response) {
    const fetchMock = vi.fn().mockImplementation(async () => make())
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
}

async function failure(promise: Promise<unknown>): Promise<unknown> {
    try {
        await promise
    } catch (error) {
        return error
    }
    throw new Error("expected a rejection")
}

describe("systemRoles api (B27)", () => {
    it("returns the parsed response on success, including stranded worlds", async () => {
        const fetchMock = stub(() =>
            new Response(
                JSON.stringify({ user_id: "u1", system_role_code: "gm", changed: false, stranded_world_ids: ["w1"] }),
                { status: 200 },
            ),
        )
        await expect(revokeSystemRole("u1", "gm", "csrf")).resolves.toEqual({
            user_id: "u1",
            system_role_code: "gm",
            changed: false,
            stranded_world_ids: ["w1"],
        })
        expect(fetchMock.mock.calls[0]![0]).toBe("/api/admin/accounts/u1/system-roles/gm/revoke")
        await expect(assignSystemRole("u1", "gm", "csrf")).resolves.toMatchObject({ changed: false })
    })

    it("carries the error envelope's code on a refusal", async () => {
        stub(() => new Response(JSON.stringify({ error: { code: "admin_grant_disabled" } }), { status: 403 }))
        const error = await failure(assignSystemRole("u1", "admin", "csrf"))
        expect(error).toBeInstanceOf(PlatformAccountsRequestError)
        expect(error).toMatchObject({ status: 403, code: "admin_grant_disabled" })
    })

    it.each([
        ["an empty body", ""],
        ["a non-JSON body", "<html>bad gateway</html>"],
        ["JSON without an error code", JSON.stringify({ detail: "x" })],
        ["a non-string code", JSON.stringify({ error: { code: 7 } })],
    ])("leaves the code undefined for %s and keeps the status", async (_name, body) => {
        stub(() => new Response(body, { status: 502 }))
        const error = (await failure(assignSystemRole("u1", "gm", "csrf"))) as PlatformAccountsRequestError
        expect(error).toBeInstanceOf(PlatformAccountsRequestError)
        expect(error.status).toBe(502)
        expect(error.code).toBeUndefined()
    })

    it("rejects an unreadable 2xx body as something other than a request refusal (unknown)", async () => {
        stub(() => new Response("not json", { status: 200 }))
        const error = await failure(assignSystemRole("u1", "gm", "csrf"))
        expect(error).not.toBeInstanceOf(PlatformAccountsRequestError)
    })

    it("rejects a 2xx body that is not a role change as unknown", async () => {
        stub(() => new Response(JSON.stringify({ ok: true }), { status: 200 }))
        const error = await failure(revokeSystemRole("u1", "gm", "csrf"))
        expect(error).not.toBeInstanceOf(PlatformAccountsRequestError)
    })
})
