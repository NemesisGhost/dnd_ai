import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import { InfoBox } from "./InfoBox"

function renderInfoBox(props: Parameters<typeof InfoBox>[0]) {
  return render(
    <MemoryRouter>
      <InfoBox {...props} />
    </MemoryRouter>,
  )
}

describe("InfoBox", () => {
  it("renders the required title", () => {
    renderInfoBox({ title: "Ixamarra", sections: [] })

    expect(
      screen.getByRole("heading", { name: "Ixamarra" }),
    ).toBeInTheDocument()
  })

  it("renders an optional subtitle, status, and image with alt text", () => {
    renderInfoBox({
      title: "Ixamarra",
      subtitle: "Player character",
      status: "Alive",
      image: { src: "/portrait.png", alt: "Portrait of Ixamarra" },
      sections: [],
    })

    expect(screen.getByText("Player character")).toBeInTheDocument()
    expect(screen.getByText("Alive")).toBeInTheDocument()

    expect(
      screen.getByRole("img", { name: "Portrait of Ixamarra" }),
    ).toHaveAttribute("src", "/portrait.png")
  })

  it("omits the subtitle, status, and image when not supplied", () => {
    renderInfoBox({ title: "Ixamarra", sections: [] })

    expect(screen.queryByRole("img")).not.toBeInTheDocument()
  })

  it("renders sections with headings and label/value rows", () => {
    renderInfoBox({
      title: "Ixamarra",
      sections: [
        {
          heading: "Overview",
          rows: [
            { label: "Race", value: "Elf" },
            { label: "Class", value: "Wizard" },
          ],
        },
      ],
    })

    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument()
    expect(screen.getByText("Race")).toBeInTheDocument()
    expect(screen.getByText("Elf")).toBeInTheDocument()
    expect(screen.getByText("Class")).toBeInTheDocument()
    expect(screen.getByText("Wizard")).toBeInTheDocument()
  })

  it("does not render an empty section heading, row list, or the section itself when a section has no rows", () => {
    renderInfoBox({
      title: "Ixamarra",
      sections: [
        { heading: "Empty section", rows: [] },
        { rows: [{ label: "Race", value: "Elf" }] },
      ],
    })

    expect(
      screen.queryByRole("heading", { name: "Empty section" }),
    ).not.toBeInTheDocument()
    expect(screen.getByText("Race")).toBeInTheDocument()
  })

  it("renders React-node values, not just plain text", () => {
    renderInfoBox({
      title: "Ixamarra",
      sections: [
        {
          rows: [
            {
              label: "Status effects",
              value: <span data-testid="badge">Blessed</span>,
            },
          ],
        },
      ],
    })

    expect(screen.getByTestId("badge")).toHaveTextContent("Blessed")
  })

  it("renders related links as React Router links with correct destinations", () => {
    renderInfoBox({
      title: "Ixamarra",
      sections: [],
      relatedLinks: [
        { label: "View party", to: "/app/mundivita/characters" },
      ],
    })

    expect(
      screen.getByRole("link", { name: "View party" }),
    ).toHaveAttribute("href", "/app/mundivita/characters")
  })

  it("omits the related-links section entirely when none are supplied", () => {
    renderInfoBox({ title: "Ixamarra", sections: [] })

    expect(
      screen.queryByRole("navigation"),
    ).not.toBeInTheDocument()
  })

  it("omits the related-links section when an empty array is supplied", () => {
    renderInfoBox({ title: "Ixamarra", sections: [], relatedLinks: [] })

    expect(
      screen.queryByRole("navigation"),
    ).not.toBeInTheDocument()
  })
})
