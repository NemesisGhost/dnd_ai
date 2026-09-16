import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { WorldRequestError } from "../api/world"
import { WorldEntityDetailBoundary } from "./WorldEntityDetailBoundary"

const { reloadMock } = vi.hoisted(() => ({
    reloadMock: vi.fn(),
}))

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

interface Fixture {
    name: string
}

beforeEach(() => {
    reloadMock.mockReset()
})

describe("WorldEntityDetailBoundary", () => {
    it("shows a loading state before the request resolves", () => {
        const fetchDetail = vi.fn().mockReturnValue(new Promise<Fixture>(() => {}))

        render(
            <WorldEntityDetailBoundary
                campaignId="campaign-a"
                entityId="entity-a"
                fetchDetail={fetchDetail}
                resourceLabel="location"
            >
                {(detail: Fixture) => <p>{detail.name}</p>}
            </WorldEntityDetailBoundary>,
        )

        expect(screen.getByText("Loading location")).toBeInTheDocument()
    })

    it("renders the children with the loaded detail on success", async () => {
        const fetchDetail = vi.fn().mockResolvedValue({ name: "The Sunken Archive" })

        render(
            <WorldEntityDetailBoundary
                campaignId="campaign-a"
                entityId="entity-a"
                fetchDetail={fetchDetail}
                resourceLabel="location"
            >
                {(detail: Fixture) => <p>{detail.name}</p>}
            </WorldEntityDetailBoundary>,
        )

        await waitFor(() => {
            expect(screen.getByText("The Sunken Archive")).toBeInTheDocument()
        })
    })

    it.each([403, 404])(
        "shows a non-disclosing unavailable state for HTTP %s",
        async (status) => {
            const fetchDetail = vi
                .fn()
                .mockRejectedValue(new WorldRequestError(status))

            render(
                <WorldEntityDetailBoundary
                    campaignId="campaign-a"
                    entityId="entity-a"
                    fetchDetail={fetchDetail}
                    resourceLabel="location"
                >
                    {(detail: Fixture) => <p>{detail.name}</p>}
                </WorldEntityDetailBoundary>,
            )

            await waitFor(() => {
                expect(
                    screen.getByText("Location unavailable"),
                ).toBeInTheDocument()
            })
        },
    )

    it("shows a recoverable error with a retry action", async () => {
        const error = new Error("boom")
        const fetchDetail = vi.fn().mockRejectedValue(error)

        render(
            <WorldEntityDetailBoundary
                campaignId="campaign-a"
                entityId="entity-a"
                fetchDetail={fetchDetail}
                resourceLabel="event"
            >
                {(detail: Fixture) => <p>{detail.name}</p>}
            </WorldEntityDetailBoundary>,
        )

        await waitFor(() => {
            expect(
                screen.getByText("Event information unavailable"),
            ).toBeInTheDocument()
        })

        expect(
            screen.getByRole("button", { name: "Try again" }),
        ).toBeInTheDocument()
    })
})
