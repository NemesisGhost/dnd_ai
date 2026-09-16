import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { FeatureCard } from "./FeatureCard"

const feature = characterSheetFixture.features[0]
describe("FeatureCard", () => {
    it.each(["class", "subclass", "species", "other"])("labels %s source", (source) => {
        render(<FeatureCard feature={{ ...feature, source_category: source }} />)
        const summary = screen.getByText(feature.display_name).closest("summary") as HTMLElement
        expect(within(summary).getByText(source.charAt(0).toUpperCase() + source.slice(1))).toBeInTheDocument()
        expect(summary.closest("details")).toBeInTheDocument()
    })
    it("shows missing-description fallback and omits null grant level", () => {
        render(<FeatureCard feature={{ ...feature, description: null, granted_at_level: null }} />)
        expect(screen.getByText("No description recorded.")).toBeInTheDocument()
        expect(screen.queryByText(/Granted at level/)).not.toBeInTheDocument()
    })
})
