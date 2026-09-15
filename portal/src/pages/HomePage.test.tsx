import {
    render,
    screen,
} from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { CampaignSummary } from "../types/campaignSummary"
import { HomePage } from "./HomePage"

const populatedSummary = {
    current_session: {
        session_id: "session-12",
        session_number: 12,
        title: "The Glass Ossuary",
        status_code: "active",
        started_at: "2026-09-04T18:00:00Z",
        ended_at: null,
    },
    previous_session_recap:
        "The party entered the dormant facility.",
    recent_events: [],
} satisfies CampaignSummary

describe("HomePage", () => {
    it("displays the latest session and previous recap", () => {
        render(
            <HomePage summary={populatedSummary} />,
        )

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Home",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                level: 2,
                name: "Latest session",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Session 12: The Glass Ossuary",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText("Status: active"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The party entered the dormant facility.",
            ),
        ).toBeInTheDocument()
    })

    it("uses the fallback for an untitled session", () => {
        render(
            <HomePage
                summary={{
                    ...populatedSummary,
                    current_session: {
                        ...populatedSummary.current_session,
                        title: null,
                    },
                }}
            />,
        )

        expect(
            screen.getByText(
                "Session 12: Untitled session",
            ),
        ).toBeInTheDocument()
    })

    it("displays deliberate empty states", () => {
        render(
            <HomePage
                summary={{
                    current_session: null,
                    previous_session_recap: null,
                    recent_events: [],
                }}
            />,
        )

        expect(
            screen.getByText(
                "No sessions have been recorded.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No previous session recap is available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(/^Status:/),
        ).not.toBeInTheDocument()
    })
})