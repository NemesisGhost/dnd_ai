import {
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { AuditHistoryPage } from "../types/auditHistory"
import { AuditHistory } from "./AuditHistory"

// Mocked only at the network boundary (global fetch) — every layer above
// it (AuditHistory -> useAuditHistory -> the auditHistory API client) runs
// for real, per this workstream's "exercise the real component -> hook ->
// API-client path" test requirement.

const reloadMock = vi.fn()

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

function pageWith(
    items: AuditHistoryPage["items"],
    nextCursor: string | null = null,
): AuditHistoryPage {
    return { items, next_cursor: nextCursor }
}

const roleChangeItem = {
    change_log_id: 42,
    occurred_at: "2026-09-18T21:04:11.123456+00:00",
    category: "role" as const,
    action_label: "Role changed",
    actor_label: "GM Alex",
    actor_type: "user" as const,
    target_label: "Player Sam",
    target_type: "account" as const,
    change_summary: "Player → Observer",
    outcome: null,
}

beforeEach(() => {
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("AuditHistory", () => {
    it("shows a loading status, then the loaded rows with no raw UUID as the only label", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(
                jsonResponse(pageWith([roleChangeItem])),
            )
        vi.stubGlobal("fetch", fetchMock)

        render(<AuditHistory campaignId="campaign-a" />)

        expect(
            screen.getByRole("status"),
        ).toHaveTextContent(/loading audit history/i)

        await waitFor(() => {
            expect(
                screen.getByText("GM Alex"),
            ).toBeInTheDocument()
        })

        expect(
            screen.getByText("Player Sam"),
        ).toBeInTheDocument()
        expect(
            screen.getByText("Role changed"),
        ).toBeInTheDocument()
        expect(
            screen.getByText("Player → Observer"),
        ).toBeInTheDocument()

        // change_log_id must never appear as visible text anywhere.
        expect(
            screen.queryByText("42"),
        ).not.toBeInTheDocument()

        // No cell renders a raw UUID as its only content.
        for (const cell of screen.getAllByRole("cell")) {
            const text = cell.textContent ?? ""
            const isRawUuid =
                /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                    text.trim(),
                )
            expect(isRawUuid).toBe(false)
        }

        expect(fetchMock).toHaveBeenCalledWith(
            expect.stringContaining(
                "/api/campaigns/campaign-a/audit-history",
            ),
            expect.objectContaining({ method: "GET" }),
        )
    })

    it("has no page-level h1 (safe to embed under an existing page heading)", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse(pageWith([])),
            ),
        )

        render(<AuditHistory campaignId="campaign-a" />)

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 2 }),
            ).toHaveTextContent("Audit history")
        })

        expect(
            screen.queryByRole("heading", { level: 1 }),
        ).not.toBeInTheDocument()
    })

    it("shows an empty-history status when the page has no items", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse(pageWith([])),
            ),
        )

        render(<AuditHistory campaignId="campaign-a" />)

        await waitFor(() => {
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent(
                /no audit history matches/i,
            )
        })
    })

    it("shows an unavailable status for a denied/nonexistent campaign", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse({ error: { code: "not_found" } }, 404),
            ),
        )

        render(<AuditHistory campaignId="campaign-a" />)

        await waitFor(() => {
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent(
                /not available for this campaign/i,
            )
        })

        expect(
            screen.queryByRole("button", { name: /try again/i }),
        ).not.toBeInTheDocument()
    })

    it("shows a recoverable error with a working retry button", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                jsonResponse({ error: { code: "internal_error" } }, 500),
            )
            .mockResolvedValueOnce(
                jsonResponse(pageWith([roleChangeItem])),
            )
        vi.stubGlobal("fetch", fetchMock)

        render(<AuditHistory campaignId="campaign-a" />)

        await waitFor(() => {
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent(/could not load audit history/i)
        })

        const retryButton = screen.getByRole("button", {
            name: /try again/i,
        })
        fireEvent.click(retryButton)

        await waitFor(() => {
            expect(
                screen.getByText("GM Alex"),
            ).toBeInTheDocument()
        })

        expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it("loads more rows via the Load more button and appends them", async () => {
        const secondItem = {
            ...roleChangeItem,
            change_log_id: 99,
            action_label: "Member added",
        }

        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(
                jsonResponse(
                    pageWith([roleChangeItem], "cursor-1"),
                ),
            )
            .mockResolvedValueOnce(
                jsonResponse(pageWith([secondItem])),
            )
        vi.stubGlobal("fetch", fetchMock)

        render(<AuditHistory campaignId="campaign-a" />)

        const loadMoreButton = await screen.findByRole(
            "button",
            { name: /load more/i },
        )

        fireEvent.click(loadMoreButton)

        await waitFor(() => {
            expect(
                screen.getByText("Member added"),
            ).toBeInTheDocument()
        })

        expect(
            screen.getByText("Role changed"),
        ).toBeInTheDocument()

        // No more pages: the button disappears once next_cursor is null.
        await waitFor(() => {
            expect(
                screen.queryByRole("button", {
                    name: /load more/i,
                }),
            ).not.toBeInTheDocument()
        })

        expect(fetchMock).toHaveBeenCalledTimes(2)
        const secondCallUrl = fetchMock.mock.calls[1]?.[0] as string
        expect(secondCallUrl).toContain("cursor=cursor-1")
    })

    it("re-requests with the selected category when filters are applied via the form", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(jsonResponse(pageWith([])))
        vi.stubGlobal("fetch", fetchMock)

        render(<AuditHistory campaignId="campaign-a" />)

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(1)
        })

        const categorySelect = screen.getByLabelText(
            "Category",
        ) as HTMLSelectElement
        fireEvent.change(categorySelect, {
            target: { value: "role" },
        })

        fireEvent.click(
            screen.getByRole("button", {
                name: /apply filters/i,
            }),
        )

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        const secondCallUrl = fetchMock.mock.calls[1]?.[0] as string
        expect(secondCallUrl).toContain("category=role")
    })

    it("clearing filters resets the request to no filters", async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(jsonResponse(pageWith([])))
        vi.stubGlobal("fetch", fetchMock)

        render(<AuditHistory campaignId="campaign-a" />)
        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(1)
        })

        const categorySelect = screen.getByLabelText(
            "Category",
        ) as HTMLSelectElement
        fireEvent.change(categorySelect, {
            target: { value: "role" },
        })
        fireEvent.click(
            screen.getByRole("button", {
                name: /apply filters/i,
            }),
        )
        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        fireEvent.click(
            screen.getByRole("button", {
                name: /clear filters/i,
            }),
        )

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(3)
        })
        const thirdCallUrl = fetchMock.mock.calls[2]?.[0] as string
        expect(thirdCallUrl).not.toContain("category=")
        expect(
            (screen.getByLabelText("Category") as HTMLSelectElement)
                .value,
        ).toBe("")
    })

    it("resets to loading and never shows a previous campaign's rows when campaignId changes while a request is pending", async () => {
        let resolveFirst:
            | ((response: Response) => void)
            | undefined
        const firstRequest = new Promise<Response>(
            (resolve) => {
                resolveFirst = resolve
            },
        )

        const fetchMock = vi
            .fn()
            .mockReturnValueOnce(firstRequest)
            .mockResolvedValueOnce(
                jsonResponse(
                    pageWith([
                        {
                            ...roleChangeItem,
                            action_label: "Campaign B event",
                        },
                    ]),
                ),
            )
        vi.stubGlobal("fetch", fetchMock)

        const { rerender } = render(
            <AuditHistory campaignId="campaign-a" />,
        )

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalledTimes(1)
        })

        rerender(<AuditHistory campaignId="campaign-b" />)

        expect(
            screen.getByRole("status"),
        ).toHaveTextContent(/loading audit history/i)

        await waitFor(() => {
            expect(
                screen.getByText("Campaign B event"),
            ).toBeInTheDocument()
        })

        // The stale campaign-a response resolving late must never appear.
        resolveFirst?.(
            jsonResponse(
                pageWith([
                    {
                        ...roleChangeItem,
                        action_label: "Stale campaign-a event",
                    },
                ]),
            ),
        )

        await waitFor(() => {
            expect(
                screen.queryByText(
                    "Stale campaign-a event",
                ),
            ).not.toBeInTheDocument()
        })
    })

    it("marks a service-attributed row distinctly without exposing anything unsafe", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse(
                    pageWith([
                        {
                            ...roleChangeItem,
                            actor_label: "importer-bot",
                            actor_type: "service" as const,
                        },
                    ]),
                ),
            ),
        )

        render(<AuditHistory campaignId="campaign-a" />)

        const row = await screen.findByText("importer-bot")
        expect(
            within(row.closest("tr") as HTMLElement).getByText(
                /\(service\)/,
            ),
        ).toBeInTheDocument()
    })
})
