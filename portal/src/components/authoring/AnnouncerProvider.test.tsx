import { act, render, screen } from "@testing-library/react"
import { useEffect } from "react"
import { describe, expect, it } from "vitest"
import { AnnouncerProvider } from "./AnnouncerProvider"
import { useAnnounce, useAnnounceOwned } from "./announcer"

// The one polite live region and who may take a message back out of it. jsdom shows what the region
// holds; it says nothing about what an assistive technology has already spoken.

const probe: {
    say: (message: string) => void
    sayOwned: (message: string) => () => void
} = {
    say: () => undefined,
    sayOwned: () => () => undefined,
}

function Probe() {
    const announce = useAnnounce()
    const announceOwned = useAnnounceOwned()
    useEffect(() => {
        probe.say = announce
        probe.sayOwned = announceOwned
    })
    return null
}
const say = (message: string) => probe.say(message)
const sayOwned = (message: string) => probe.sayOwned(message)
const noop = (): void => undefined

const region = () => screen.getByTestId("authoring-announcer").textContent

function mount() {
    render(
        <AnnouncerProvider>
            <Probe />
        </AnnouncerProvider>,
    )
}

describe("AnnouncerProvider withdrawal", () => {
    it("withdrawing the latest message empties the region", () => {
        mount()
        let withdraw = noop
        act(() => {
            withdraw = sayOwned("Viewing as Sam.")
        })
        expect(region()).toBe("Viewing as Sam.")

        act(() => withdraw())

        expect(region()).toBe("")
    })

    it("never removes a newer message, whoever made it", () => {
        mount()
        let withdraw = noop
        act(() => {
            withdraw = sayOwned("Viewing as Sam.")
        })
        act(() => say("Saved."))

        act(() => withdraw())

        expect(region()).toBe("Saved.")
    })

    it("never removes a newer owned message, and the older owner's cleanup done twice does nothing", () => {
        mount()
        let first = noop
        let second = noop
        act(() => {
            first = sayOwned("World changed to Alder.")
        })
        act(() => {
            second = sayOwned("Viewing as Sam.")
        })

        act(() => first())
        act(() => first())
        expect(region()).toBe("Viewing as Sam.")

        act(() => second())
        act(() => say("Saved."))
        act(() => second())
        expect(region()).toBe("Saved.")
    })

    it("an announcer that is only an `announce` still works for an owner, which then cannot withdraw", () => {
        render(<Probe />)
        expect(() => sayOwned("x")()).not.toThrow()
    })
})
