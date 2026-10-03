import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { GlobalNavigation } from "./GlobalNavigation"

function renderNavigation(initialEntry = "/home") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <GlobalNavigation />
    </MemoryRouter>,
  )
}

describe("GlobalNavigation", () => {
  it("renders the Global landmark with Home and Campaigns links", () => {
    renderNavigation()

    const nav = screen.getByRole("navigation", { name: "Global" })

    expect(
      within(nav).getByRole("link", { name: "Home" }),
    ).toHaveAttribute("href", "/home")

    expect(
      within(nav).getByRole("link", { name: "Campaigns" }),
    ).toHaveAttribute("href", "/campaigns")
  })

  it("marks the current destination with aria-current", () => {
    renderNavigation("/campaigns")

    const nav = screen.getByRole("navigation", { name: "Global" })

    expect(
      within(nav).getByRole("link", { name: "Campaigns" }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      within(nav).getByRole("link", { name: "Home" }),
    ).not.toHaveAttribute("aria-current")
  })
})
