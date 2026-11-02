import { afterEach, describe, expect, it, vi } from "vitest"
import { createAccount } from "./createAccount"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("createAccount", () => {
    it("posts login_name/display_name/email with csrf and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    user_id: "user-1",
                    login_name: "new.gm",
                    raw_activation_token: "raw-activation-token",
                    expires_at: "2026-10-01T00:00:00Z",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            createAccount("new.gm", "New GM", "gm@example.com", ["gm"], "csrf-token"),
        ).resolves.toEqual({
            user_id: "user-1",
            login_name: "new.gm",
            raw_activation_token: "raw-activation-token",
            expires_at: "2026-10-01T00:00:00Z",
        })

        expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: undefined,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRF-Token": "csrf-token",
            },
            body: JSON.stringify({
                login_name: "new.gm",
                display_name: "New GM",
                email: "gm@example.com",
                system_role_codes: ["gm"],
            }),
        })
    })
})
