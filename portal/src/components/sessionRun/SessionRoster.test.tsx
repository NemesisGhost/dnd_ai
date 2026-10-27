import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { SessionParticipant } from "../../types/campaignSession"
import { SessionRoster } from "./SessionRoster"

const person = (overrides: Partial<SessionParticipant> & { session_participant_id: string }): SessionParticipant => ({
    character_id: "c1",
    character_name: "Cael",
    character_kind: "player_character",
    participation_role: "player_character",
    added_at: "2026-10-12T19:00:00Z",
    removed_at: null,
    ...overrides,
})

const renderRoster = (participants: SessionParticipant[], controls?: (p: SessionParticipant) => React.ReactNode) =>
    render(
        <MemoryRouter>
            <SessionRoster campaignId="mundivita" participants={participants} controls={controls} />
        </MemoryRouter>,
    )

describe("SessionRoster", () => {
    it("shows a name without a link when the server says the character cannot be opened", () => {
        renderRoster([
            person({ session_participant_id: "p1", can_open_character: false }),
            person({ session_participant_id: "p2", character_id: "c2", character_name: "Dara", can_open_character: true }),
        ])
        expect(screen.queryByRole("link", { name: "Cael" })).toBeNull()
        expect(screen.getByText(/Cael/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Dara" })).toBeInTheDocument()
    })

    it("says so when nobody is in the session", () => {
        renderRoster([])
        expect(screen.getByText("No one is in this session yet.")).toBeInTheDocument()
    })

    it("shows name, structured kind, role, status and real times, with a character link", () => {
        const { container } = renderRoster([
            person({ session_participant_id: "p1" }),
            person({
                session_participant_id: "p2",
                character_id: "c2",
                character_name: "Visitor",
                character_kind: "npc",
                participation_role: "guest",
                removed_at: "2026-10-12T20:30:00Z",
            }),
        ])
        const [cael, visitor] = screen.getAllByRole("listitem")
        expect(cael).toHaveTextContent("Cael (Player character; role: Player character). Present.")
        expect(cael).toHaveTextContent("Added:")
        expect(cael).not.toHaveTextContent("Removed:")
        // A guest keeps the kind of the character, which the role never changes.
        expect(visitor).toHaveTextContent("Visitor (NPC; role: Guest). Left.")
        expect(visitor).toHaveTextContent("Removed:")
        expect(within(cael!).getByRole("link", { name: "Cael" })).toHaveAttribute(
            "href",
            "/app/mundivita/characters/c1",
        )
        expect(container.querySelector('time[datetime="2026-10-12T20:30:00Z"]')).toBeInTheDocument()
    })

    it("keeps removed and re-added stints of one character as separate rows, present first", () => {
        renderRoster([
            person({ session_participant_id: "old", participation_role: "guest", removed_at: "2026-10-12T20:00:00Z" }),
            person({ session_participant_id: "new", added_at: "2026-10-12T20:10:00Z" }),
        ])
        const rows = screen.getAllByRole("listitem")
        expect(rows).toHaveLength(2)
        expect(rows[0]).toHaveTextContent("Present.")
        expect(rows[1]).toHaveTextContent("Left.")
    })

    it("offers controls for present rows only, and none when no controls are given", () => {
        const people = [
            person({ session_participant_id: "p1" }),
            person({ session_participant_id: "p2", character_name: "Gone", removed_at: "2026-10-12T20:00:00Z" }),
        ]
        const { unmount } = renderRoster(people, (p) => <button type="button">Remove {p.character_name}</button>)
        expect(screen.getByRole("button", { name: "Remove Cael" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Remove Gone" })).toBeNull()
        unmount()
        renderRoster(people)
        expect(screen.queryByRole("button")).toBeNull()
    })
})
