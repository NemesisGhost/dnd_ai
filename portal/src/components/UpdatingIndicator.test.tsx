import {
    act,
    render,
    screen,
} from "@testing-library/react"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { UpdatingIndicator } from "./UpdatingIndicator"

describe("UpdatingIndicator", () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it("renders nothing immediately", () => {
        render(<UpdatingIndicator />)

        expect(
            screen.queryByText("Updating results…"),
        ).not.toBeInTheDocument()
    })

    it("renders the updating message once the delay elapses", () => {
        render(<UpdatingIndicator />)

        act(() => {
            vi.advanceTimersByTime(200)
        })

        expect(
            screen.getByRole("status"),
        ).toHaveTextContent("Updating results…")
    })

    it("clears its pending timer on unmount so it never sets state afterward", () => {
        const errorSpy = vi
            .spyOn(console, "error")
            .mockImplementation(() => { })

        const { unmount } = render(<UpdatingIndicator />)

        unmount()

        act(() => {
            vi.advanceTimersByTime(200)
        })

        expect(errorSpy).not.toHaveBeenCalled()

        errorSpy.mockRestore()
    })
})
