import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { EMPTY_AUDIT_HISTORY_FILTERS } from "../types/auditHistory"
import type { AuditHistoryPage } from "../types/auditHistory"
import {
    AuditHistoryRequestError,
    fetchAuditHistory,
} from "./auditHistory"

const pageFixture = {
    items: [
        {
            change_log_id: 42,
            occurred_at: "2026-09-18T21:04:11.123456+00:00",
            category: "role",
            action_label: "Role changed",
            actor_label: "GM Alex",
            actor_type: "user",
            target_label: "Player Sam",
            target_type: "account",
            change_summary: "Player → Observer",
            outcome: null,
        },
    ],
    next_cursor: "opaque-cursor",
} satisfies AuditHistoryPage

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchAuditHistory", () => {
    it("returns a page and encodes every filter parameter", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(pageFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchAuditHistory(
                "campaign/a b",
                {
                    category: "role",
                    actorUserId: "user-1",
                    occurredFrom: "2026-01-01T00:00:00Z",
                    occurredTo: "2026-12-31T23:59:59Z",
                },
                "prior-cursor",
                controller.signal,
                50,
            ),
        ).resolves.toEqual(pageFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)
        const [calledUrl, calledInit] = fetchMock.mock.calls[0] as [
            string,
            RequestInit,
        ]
        expect(calledUrl).toContain(
            "/api/campaigns/campaign%2Fa%20b/audit-history?",
        )
        expect(calledUrl).toContain("category=role")
        expect(calledUrl).toContain("actor_user_id=user-1")
        expect(calledUrl).toContain(
            "occurred_from=2026-01-01T00%3A00%3A00Z",
        )
        expect(calledUrl).toContain(
            "occurred_to=2026-12-31T23%3A59%3A59Z",
        )
        expect(calledUrl).toContain("cursor=prior-cursor")
        expect(calledUrl).toContain("limit=50")
        expect(calledInit).toEqual({
            method: "GET",
            headers: { Accept: "application/json" },
            cache: "no-store",
            signal: controller.signal,
        })
    })

    it("omits every empty/null optional parameter", async () => {
        const emptyPage = {
            items: [],
            next_cursor: null,
        } satisfies AuditHistoryPage

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(emptyPage), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchAuditHistory(
                "campaign-a",
                EMPTY_AUDIT_HISTORY_FILTERS,
                null,
            ),
        ).resolves.toEqual(emptyPage)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/audit-history",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws AuditHistoryRequestError with the response status on failure", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    error: {
                        code: "forbidden",
                        message: "no",
                        correlation_id: "x",
                    },
                }),
                { status: 403 },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        const error = await fetchAuditHistory(
            "campaign-a",
            EMPTY_AUDIT_HISTORY_FILTERS,
            null,
        ).catch((caught: unknown) => caught)

        expect(error).toBeInstanceOf(AuditHistoryRequestError)
        expect((error as AuditHistoryRequestError).status).toBe(403)
    })
})
