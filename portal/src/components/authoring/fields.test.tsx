import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { RadioGroupField, SelectField, TextAreaField, TextField } from "./fields"

describe("TextField", () => {
    it("has a visible label bound to the input and marks required fields", () => {
        render(<TextField label="World name" value="" onChange={() => {}} required />)
        const input = screen.getByRole("textbox", { name: /World name/ })
        expect(input).toHaveAttribute("aria-required", "true")
        expect(screen.getByText("(required)")).toBeInTheDocument()
    })

    it("wires the hint and error to the control and flags it invalid, with plain-text error", () => {
        render(
            <TextField
                id="n"
                label="Name"
                value=""
                onChange={() => {}}
                hint="Shown in lists"
                error="Name is required."
            />,
        )
        const input = screen.getByRole("textbox", { name: "Name" })
        expect(input).toHaveAttribute("aria-invalid", "true")
        expect(input.getAttribute("aria-describedby")).toBe("n-hint n-error")
        expect(document.getElementById("n-hint")).toHaveTextContent("Shown in lists")
        // The error is words, not just a color.
        expect(document.getElementById("n-error")).toHaveTextContent("Error: Name is required.")
    })

    it("is not invalid without an error", () => {
        render(<TextField label="Name" value="x" onChange={() => {}} />)
        expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-invalid")
        expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-describedby")
    })

    it("reports changes", () => {
        const onChange = vi.fn()
        render(<TextField label="Name" value="" onChange={onChange} />)
        fireEvent.change(screen.getByRole("textbox"), { target: { value: "abc" } })
        expect(onChange).toHaveBeenCalledWith("abc")
    })

    it("shows a polite character counter only near the limit", () => {
        const { rerender } = render(
            <TextField label="Name" value="short" onChange={() => {}} maxLength={200} />,
        )
        expect(screen.queryByText(/characters remaining/)).not.toBeInTheDocument()

        rerender(<TextField label="Name" value={"x".repeat(185)} onChange={() => {}} maxLength={200} />)
        expect(screen.getByText("15 characters remaining")).toHaveAttribute("aria-live", "polite")

        rerender(<TextField label="Name" value={"x".repeat(205)} onChange={() => {}} maxLength={200} />)
        expect(screen.getByText("5 characters over the limit")).toBeInTheDocument()
    })
})

describe("TextAreaField", () => {
    it("is a labeled multi-line control with the same error wiring", () => {
        render(
            <TextAreaField id="d" label="Description" value="" onChange={() => {}} error="Too long" />,
        )
        const area = screen.getByRole("textbox", { name: "Description" })
        expect(area.tagName).toBe("TEXTAREA")
        expect(area).toHaveAttribute("aria-invalid", "true")
        expect(area.getAttribute("aria-describedby")).toBe("d-error")
    })
})

describe("SelectField", () => {
    it("renders a labeled select with a placeholder and options", () => {
        const onChange = vi.fn()
        render(
            <SelectField
                label="Default ruleset"
                value=""
                placeholder="Choose"
                options={[{ value: "a", label: "Alpha" }]}
                onChange={onChange}
            />,
        )
        const select = screen.getByRole("combobox", { name: "Default ruleset" })
        expect(screen.getByRole("option", { name: "Choose" })).toBeInTheDocument()
        fireEvent.change(select, { target: { value: "a" } })
        expect(onChange).toHaveBeenCalledWith("a")
    })
})

describe("RadioGroupField", () => {
    it("is a fieldset with a legend, one checked radio, and an accessible error", () => {
        const onChange = vi.fn()
        render(
            <RadioGroupField
                legend="Branch from"
                value="latest"
                options={[
                    { value: "latest", label: "Latest", description: "The present state." },
                    { value: "existing", label: "Existing" },
                ]}
                onChange={onChange}
                error="Pick one"
            />,
        )
        const group = screen.getByRole("group", { name: "Branch from" })
        expect(group).toHaveAttribute("aria-invalid", "true")
        expect(screen.getByRole("radio", { name: "Latest" })).toBeChecked()
        fireEvent.click(screen.getByRole("radio", { name: "Existing" }))
        expect(onChange).toHaveBeenCalledWith("existing")
        expect(screen.getByText("The present state.")).toBeInTheDocument()
        expect(group).toHaveTextContent("Error: Pick one")
    })
})
