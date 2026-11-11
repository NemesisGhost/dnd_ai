import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useMemo, useState, useSyncExternalStore } from "react"
import { Link, Route, RouterProvider, Routes, createMemoryRouter, useLocation, useParams } from "react-router"
import type { DataRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { installNativeDialogModel } from "../test/nativeDialog"
import { useAcceptedNavigation } from "../components/useSidebarMenu"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { ArrivalHeadingFocus } from "./ArrivalHeadingFocus"
import { SelectionArrivalContext } from "./selectionArrival"
import { createArrivalTracker } from "./selectionArrivalTracker"

// The hand-off of the control a navigation was requested with, from the accepted request to its arrival
// (navigation/activationOwner.ts). The production shell remounts its sidebar when the campaign scope
// changes, so there the activated control never survives a campaign change and the hand-off cannot be seen
// working. This tree keeps the menu links mounted across the navigation, and runs the real router, the real
// `useAcceptedNavigation` (the P02-4 attempt lifecycle), the real arrival tracker, the real
// `ArrivalHeadingFocus` and the real unsaved-changes guard. Context eligibility has its own tests; here the
// provider simply exposes the tracker's arrival.

configure({ asyncUtilTimeout: 5000 })

let router: DataRouter

// Whether the destination has finished loading, controlled by the test.
let loaded = true
const listeners = new Set<() => void>()
const setLoaded = (value: boolean) => {
  loaded = value
  listeners.forEach((listener) => listener())
}
const useLoaded = () =>
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => loaded,
  )

const note = (id: string) => ({ selection: { level: "campaign", id } })

function Home() {
  const { campaignId } = useParams()
  const ready = useLoaded()
  return ready ? (
    <>
      <h1>Home {campaignId}</h1>
      <ArrivalHeadingFocus />
    </>
  ) : (
    <p data-page-loading="true">Loading</p>
  )
}

function Shell() {
  const [draft, setDraft] = useState("")
  const guard = useUnsavedChangesGuard(draft !== "")
  const { begin } = useAcceptedNavigation({ onAccepted: () => undefined, opener: () => null })
  const [tracker] = useState(() => createArrivalTracker(router, () => null))
  const arrival = useSyncExternalStore(tracker.subscribe, tracker.getSnapshot)
  const { key } = useLocation()
  const value = useMemo(() => (arrival === null ? null : { arrival, locationKey: key }), [arrival, key])
  return (
    <SelectionArrivalContext.Provider value={value}>
      <nav aria-label="Menu">
        <Link to="/app/beta/home" state={note("beta")} onClick={(event) => begin(event, "/app/beta/home")}>
          Open beta
        </Link>
        <Link to="/app/gamma/home" state={note("gamma")} onClick={(event) => begin(event, "/app/gamma/home")}>
          Open gamma
        </Link>
        {/* Asks the router for beta's Home but recorded the request for another address. */}
        <Link to="/app/beta/home" state={note("beta")} onClick={(event) => begin(event, "/app/beta/home?tab=1")}>
          Mismatched beta
        </Link>
        <label>
          Draft
          <input value={draft} onChange={(event) => setDraft(event.target.value)} />
        </label>
      </nav>
      <div className="campaign-workspace__content">
        <Routes>
          <Route path="/app/:campaignId/home" element={<Home />} />
          <Route path="*" element={<h1>Start</h1>} />
        </Routes>
      </div>
      <ConfirmDialog
        open={guard.blocked}
        title="Discard your draft?"
        description="unsent"
        confirmLabel="Leave"
        cancelLabel="Stay"
        onConfirm={guard.discard}
        onCancel={guard.stay}
      />
    </SelectionArrivalContext.Provider>
  )
}

function mount() {
  router = createMemoryRouter([{ path: "*", element: <Shell /> }], { initialEntries: ["/start"] })
  return render(<RouterProvider router={router} />)
}

beforeEach(() => {
  setLoaded(true)
})

const menu = () => within(screen.getByRole("navigation", { name: "Menu" }))
const link = (name: string) => menu().getByRole("link", { name })
// A pointer click: the browser focuses the control it is made on, then clicks it.
const press = (element: HTMLElement) => {
  act(() => element.focus())
  fireEvent.click(element, { detail: 1 })
}
const heading = (name: string) => screen.findByRole("heading", { level: 1, name })
const answer = async (name: "Stay" | "Leave") => {
  const dialog = await screen.findByRole("dialog", { name: "Discard your draft?" })
  fireEvent.click(within(dialog).getByRole("button", { name }))
}

describe("the activated control survives the navigation and hands focus to its own arrival", () => {
  it("accepted: the heading takes focus from the very link the request was made with", async () => {
    mount()
    const opener = link("Open beta")

    press(opener)

    const home = await heading("Home beta")
    await waitFor(() => expect(home).toHaveFocus())
    expect(opener.isConnected).toBe(true)
  })

  it("deferred: the link keeps focus while loading, and the settled heading takes it once", async () => {
    mount()
    setLoaded(false)
    const opener = link("Open beta")

    press(opener)
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/beta/home"))
    await act(async () => undefined)
    expect(opener).toHaveFocus()

    act(() => setLoaded(true))
    const home = await heading("Home beta")
    await waitFor(() => expect(home).toHaveFocus())
  })

  it("a person who moved focus to another menu link while it loaded keeps it", async () => {
    mount()
    setLoaded(false)
    press(link("Open beta"))
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/beta/home"))
    const other = link("Open gamma")
    act(() => other.focus())

    act(() => setLoaded(true))
    await heading("Home beta")
    await act(async () => undefined)

    expect(other).toHaveFocus()
  })

  it("Stay: nothing was accepted, so a later unrelated arrival at the same path gets no focus from that link", async () => {
    mount()
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })
    const opener = link("Open beta")

    press(opener)
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(opener).toHaveFocus())
    expect(router.state.location.pathname).toBe("/start")

    // The draft is gone, then something else (not that request) arrives at the same pathname.
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "" } })
    act(() => opener.focus())
    await act(async () => {
      await router.navigate("/app/beta/home", { state: note("beta") })
    })
    const home = await heading("Home beta")
    await act(async () => undefined)

    expect(home).not.toHaveFocus()
    expect(opener).toHaveFocus()
  })

  it("a request recorded for another full destination binds nothing to an arrival at this path", async () => {
    mount()
    const opener = link("Mismatched beta")

    press(opener)

    const home = await heading("Home beta")
    await act(async () => undefined)
    expect(router.state.location.pathname).toBe("/app/beta/home")
    expect(home).not.toHaveFocus()
    expect(opener).toHaveFocus()
  })

  it("a request answered Stay and superseded by another: only the accepted one hands over", async () => {
    mount()
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })

    press(link("Open beta"))
    await answer("Stay")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    // The draft is saved elsewhere; the next request is accepted without a question.
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "" } })
    press(link("Open gamma"))

    const home = await heading("Home gamma")
    await waitFor(() => expect(home).toHaveFocus())
    expect(router.state.location.pathname).toBe("/app/gamma/home")
  })

  it("guarded Leave: the accepted request's destination heading ends with the focus", async () => {
    mount()
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })
    const opener = link("Open beta")

    press(opener)
    await answer("Leave")

    const home = await heading("Home beta")
    await act(async () => undefined)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(router.state.location.pathname).toBe("/app/beta/home")
    expect(home).toHaveFocus()
  })
})

// The same guarded Leave when the dialog's native close restores focus to the element focused before
// showModal() (modeled in test/nativeDialog.ts; jsdom has no native close). Modeled evidence, not a browser run.
describe("guarded Leave with a native close that restores the opener", () => {
  let uninstall: () => void
  beforeEach(() => {
    uninstall = installNativeDialogModel()
  })
  afterEach(() => uninstall())

  it("the destination heading ends with the focus, not the surviving link", async () => {
    mount()
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })
    const opener = link("Open beta")

    press(opener)
    await answer("Leave")

    const home = await heading("Home beta")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(home).toHaveFocus())
    expect(opener.isConnected).toBe(true)
  })

  it("Leave closes before the destination has loaded: the link has focus meanwhile and the arrival takes it once", async () => {
    mount()
    setLoaded(false)
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })
    const opener = link("Open beta")

    press(opener)
    await answer("Leave")
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/beta/home"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(opener).toHaveFocus()

    act(() => setLoaded(true))
    const home = await heading("Home beta")
    await waitFor(() => expect(home).toHaveFocus())
  })

  it("Stay returns focus to the link and navigates nowhere", async () => {
    mount()
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsent" } })
    const opener = link("Open beta")

    press(opener)
    await answer("Stay")

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(opener).toHaveFocus())
    expect(router.state.location.pathname).toBe("/start")
  })
})
