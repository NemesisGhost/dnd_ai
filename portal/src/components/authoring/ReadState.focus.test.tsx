import { act, fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { StaleReadNotice } from "../StaleReadNotice"
import { ReadFailedNotice } from "./ReadState"

// Focus recovery for a retry control that is replaced (docs/UI_DESIGN.md §5.11): bounded to a
// person who used it and still held focus; a background removal or a rerender never moves focus.

function Page({ onRetry, stale = false }: { onRetry: () => Promise<unknown>; stale?: boolean }) {
  const [failed, setFailed] = useState(true)
  const [tick, setTick] = useState(0)
  return (
    <section className="authoring-page">
      <h1 tabIndex={-1}>Page</h1>
      <button type="button" onClick={() => setFailed(false)}>
        background success
      </button>
      <button type="button" onClick={() => setTick(tick + 1)}>
        rerender {tick}
      </button>
      <a href="#elsewhere">elsewhere</a>
      {failed ? (
        stale ? (
          <StaleReadNotice
            what="thing"
            onRetry={() => {
              void onRetry().then(() => setFailed(false))
            }}
          />
        ) : (
          <ReadFailedNotice
            what="thing"
            onRetry={() => onRetry().then(() => setFailed(false))}
          />
        )
      ) : (
        <p>loaded</p>
      )}
    </section>
  )
}

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
const open = (props: Parameters<typeof Page>[0]) =>
  render(
    <MemoryRouter>
      <Page {...props} />
    </MemoryRouter>,
  )

describe.each([
  ["ReadFailedNotice", false],
  ["StaleReadNotice", true],
])("%s focus recovery", (_name, stale) => {
  it("hands focus to the heading after a used retry succeeds", async () => {
    open({ onRetry: () => Promise.resolve(), stale })
    screen.getByRole("button", { name: "Try again" }).focus()
    fireEvent.click(screen.getByRole("button", { name: /Try again|Loading…/ }))
    await screen.findByText("loaded")
    await settle()
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus()
  })

  it("does nothing when the button was never used", async () => {
    open({ onRetry: () => Promise.resolve(), stale })
    screen.getByRole("button", { name: "Try again" }).focus()
    // The notice goes away without the person's retry (a background read succeeded).
    fireEvent.click(screen.getByRole("button", { name: "background success" }))
    await screen.findByText("loaded")
    await settle()
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveFocus()
  })

  it("does nothing when focus left the button after it was used", async () => {
    let release: () => void = () => {}
    open({ onRetry: () => new Promise<void>((resolve) => (release = resolve)), stale })
    screen.getByRole("button", { name: "Try again" }).focus()
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    screen.getByRole("link", { name: "elsewhere" }).focus()
    release()
    await screen.findByText("loaded")
    await settle()
    expect(screen.getByRole("link", { name: "elsewhere" })).toHaveFocus()
  })

  it("never moves focus on an ordinary rerender", async () => {
    open({ onRetry: () => Promise.resolve(), stale })
    const retry = screen.getByRole("button", { name: "Try again" })
    retry.focus()
    fireEvent.click(screen.getByRole("button", { name: /rerender/ }))
    await settle()
    expect(retry).toHaveFocus()
  })
})
