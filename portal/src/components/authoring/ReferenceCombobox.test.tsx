import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { ReferenceCombobox } from "./ReferenceCombobox"
import type { ReferenceOption } from "./ReferenceCombobox"

const OPTIONS: ReferenceOption[] = [
    { id: "a", label: "Ashen Vale", detail: "Region" },
    { id: "b", label: "Brindlemoor", detail: "Settlement" },
    { id: "c", label: "Cinder Keep", detail: "Building" },
]

type Search = (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>

function Harness({
    search,
    initial = null,
    onSubmit,
}: {
    search: Search
    initial?: ReferenceOption | null
    onSubmit?: () => void
}) {
    const [value, setValue] = useState<ReferenceOption | null>(initial)
    return (
        <form
            onSubmit={(event) => {
                event.preventDefault()
                onSubmit?.()
            }}
        >
            <ReferenceCombobox
                id="parent"
                label="Contained in"
                value={value}
                onChange={setValue}
                search={search}
            />
            <span data-testid="chosen">{value?.id ?? "none"}</span>
        </form>
    )
}

const combobox = () => screen.getByRole("combobox", { name: "Contained in" })

describe("ReferenceCombobox", () => {
    it("is a labelled combobox that starts collapsed", () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} />)
        expect(combobox()).toHaveAttribute("aria-expanded", "false")
        expect(combobox()).toHaveAttribute("aria-autocomplete", "list")
        expect(screen.queryByRole("option")).toBeNull()
    })

    it("loads options when focused and exposes them as a listbox", async () => {
        const search = vi.fn(async () => OPTIONS)
        render(<Harness search={search} />)
        fireEvent.focus(combobox())

        expect(await screen.findAllByRole("option")).toHaveLength(3)
        expect(search).toHaveBeenCalledWith("", expect.any(AbortSignal))
        expect(combobox()).toHaveAttribute("aria-expanded", "true")
        expect(combobox()).toHaveAttribute(
            "aria-controls",
            screen.getByRole("listbox", { name: "Contained in" }).id,
        )
        expect(screen.getByRole("status")).toHaveTextContent("3 options available")
    })

    it("moves with the arrow keys, wraps, and tracks the active option", async () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} />)
        fireEvent.focus(combobox())
        await screen.findAllByRole("option")
        const optionId = (index: number) => screen.getAllByRole("option")[index]!.id

        expect(combobox()).toHaveAttribute("aria-activedescendant", optionId(0))
        fireEvent.keyDown(combobox(), { key: "ArrowDown" })
        expect(combobox()).toHaveAttribute("aria-activedescendant", optionId(1))
        fireEvent.keyDown(combobox(), { key: "ArrowDown" })
        fireEvent.keyDown(combobox(), { key: "ArrowDown" })
        expect(combobox()).toHaveAttribute("aria-activedescendant", optionId(0))
        fireEvent.keyDown(combobox(), { key: "ArrowUp" })
        expect(combobox()).toHaveAttribute("aria-activedescendant", optionId(2))
    })

    it("chooses the active option with Enter without submitting the form", async () => {
        const onSubmit = vi.fn()
        render(<Harness search={vi.fn(async () => OPTIONS)} onSubmit={onSubmit} />)
        fireEvent.focus(combobox())
        await screen.findAllByRole("option")
        fireEvent.keyDown(combobox(), { key: "ArrowDown" })
        fireEvent.keyDown(combobox(), { key: "Enter" })

        expect(screen.getByTestId("chosen")).toHaveTextContent("b")
        expect(combobox()).toHaveValue("Brindlemoor")
        expect(combobox()).toHaveAttribute("aria-expanded", "false")
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it("chooses with a click", async () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} />)
        fireEvent.focus(combobox())
        fireEvent.click((await screen.findAllByRole("option"))[2]!)
        expect(screen.getByTestId("chosen")).toHaveTextContent("c")
    })

    it("closes with Escape and restores the chosen name instead of keeping typed text", async () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} initial={OPTIONS[0]!} />)
        expect(combobox()).toHaveValue("Ashen Vale")
        fireEvent.focus(combobox())
        fireEvent.change(combobox(), { target: { value: "zzz" } })
        expect(combobox()).toHaveValue("zzz")
        fireEvent.keyDown(combobox(), { key: "Escape" })

        expect(combobox()).toHaveAttribute("aria-expanded", "false")
        expect(combobox()).toHaveValue("Ashen Vale")
        expect(screen.getByTestId("chosen")).toHaveTextContent("a")
    })

    it("never accepts free text: blurring restores the value", async () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} />)
        fireEvent.focus(combobox())
        fireEvent.change(combobox(), { target: { value: "typed" } })
        fireEvent.blur(combobox())
        expect(combobox()).toHaveValue("")
        expect(screen.getByTestId("chosen")).toHaveTextContent("none")
    })

    it("debounces typing into one search with the final text", async () => {
        const search = vi.fn(async () => OPTIONS)
        render(<Harness search={search} />)
        fireEvent.focus(combobox())
        await screen.findAllByRole("option")
        search.mockClear()

        fireEvent.change(combobox(), { target: { value: "a" } })
        fireEvent.change(combobox(), { target: { value: "as" } })
        fireEvent.change(combobox(), { target: { value: "ash" } })
        expect(search).not.toHaveBeenCalled()
        await waitFor(() => expect(search).toHaveBeenCalledTimes(1))
        expect(search).toHaveBeenCalledWith("ash", expect.any(AbortSignal))
    })

    it("aborts a superseded search and discards its late response", async () => {
        const resolvers: Record<string, (options: ReferenceOption[]) => void> = {}
        const signals: Record<string, AbortSignal> = {}
        const search: Search = (query, signal) =>
            new Promise((resolve) => {
                resolvers[query] = resolve
                signals[query] = signal
            })
        render(<Harness search={search} />)
        fireEvent.focus(combobox())
        await waitFor(() => expect(resolvers[""]).toBeDefined())
        fireEvent.change(combobox(), { target: { value: "b" } })
        await waitFor(() => expect(resolvers["b"]).toBeDefined())
        expect(signals[""]!.aborted).toBe(true)

        await act(async () => {
            resolvers["b"]!([OPTIONS[1]!])
        })
        await act(async () => {
            resolvers[""]!(OPTIONS)
        })
        expect(screen.getAllByRole("option")).toHaveLength(1)
        expect(screen.getByRole("option")).toHaveTextContent("Brindlemoor")
    })

    it("reports an empty result and a failure, and retries", async () => {
        const search = vi
            .fn<Search>()
            .mockRejectedValueOnce(new Error("boom"))
            .mockResolvedValueOnce([])
        render(<Harness search={search} />)
        fireEvent.focus(combobox())
        expect(await screen.findByText("Options could not be loaded.")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        expect(await screen.findByText("No matches.")).toBeInTheDocument()
        expect(screen.getByRole("status")).toHaveTextContent("No matches")
    })

    it("clears the chosen record with an explicitly labelled button", async () => {
        render(<Harness search={vi.fn(async () => OPTIONS)} initial={OPTIONS[0]!} />)
        fireEvent.click(screen.getByRole("button", { name: "Clear Contained in" }))
        expect(screen.getByTestId("chosen")).toHaveTextContent("none")
        expect(screen.queryByRole("button", { name: /Clear/ })).toBeNull()
    })

    it("aborts its in-flight search when unmounted", async () => {
        let signal: AbortSignal | undefined
        const search: Search = (_query, s) => {
            signal = s
            return new Promise(() => {})
        }
        const { unmount } = render(<Harness search={search} />)
        fireEvent.focus(combobox())
        await waitFor(() => expect(signal).toBeDefined())
        unmount()
        expect(signal!.aborted).toBe(true)
    })

    it("shows the error text and links it to the input", () => {
        render(
            <ReferenceCombobox
                id="parent"
                label="Contained in"
                value={null}
                onChange={() => {}}
                search={async () => []}
                error="That parent is not valid."
            />,
        )
        expect(combobox()).toHaveAttribute("aria-invalid", "true")
        const describedBy = combobox().getAttribute("aria-describedby")
        expect(describedBy).toBeTruthy()
        expect(document.getElementById(describedBy!)).toHaveTextContent("That parent is not valid.")
    })
})
