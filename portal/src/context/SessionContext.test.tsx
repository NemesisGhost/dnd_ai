import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
    useSessionBootstrap,
} from "../hooks/useSessionBootstrap"
import { useSession } from "./SessionContext"
import { SessionProvider } from "./SessionProvider"

vi.mock("../hooks/useSessionBootstrap", () => ({
    useSessionBootstrap: vi.fn(),
}))

const useSessionBootstrapMock = vi.mocked(
    useSessionBootstrap,
)

beforeEach(() => {
    useSessionBootstrapMock.mockReset()
})

function SessionConsumer() {
    const { state, reload } = useSession()

    return (
        <>
            <p>Session status: {state.status}</p>

            <button type="button" onClick={reload}>
                Reload session
            </button>
        </>
    )
}

describe("SessionProvider", () => {
    it("provides session state and reload to its children", () => {
        const reload = vi.fn()

        useSessionBootstrapMock.mockReturnValue({
            state: {
                status: "unauthenticated",
            },
            reload,
        })

        render(
            <SessionProvider>
                <SessionConsumer />
            </SessionProvider>,
        )

        expect(
            screen.getByText("Session status: unauthenticated"),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Reload session",
            }),
        )

        expect(reload).toHaveBeenCalledTimes(1)
    })
})