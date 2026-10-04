import { render } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { describe, expect, it, vi } from "vitest"
import { useAuthenticatedSession } from "./useAuthenticatedSession"

function Probe() {
  useAuthenticatedSession()
  return <p>rendered</p>
}

describe("useAuthenticatedSession", () => {
  it("fails with a deliberate message outside the shell's outlet context", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    expect(() =>
      render(
        <MemoryRouter>
          <Routes>
            <Route path="*" element={<Probe />} />
          </Routes>
        </MemoryRouter>,
      ),
    ).toThrow(/must be used in a route rendered through AuthenticatedAppLayout/)
    spy.mockRestore()
  })
})
