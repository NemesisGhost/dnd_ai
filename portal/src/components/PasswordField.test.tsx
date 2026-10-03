import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { PasswordField } from "./PasswordField"

describe("PasswordField", () => {
    it("renders a password input with the given label and autocomplete", () => {
        render(
            <PasswordField
                id="new-password"
                label="New password"
                value=""
                onChange={vi.fn()}
                autoComplete="new-password"
                minLength={15}
            />,
        )

        const input = screen.getByLabelText("New password")
        expect(input).toHaveAttribute("type", "password")
        expect(input).toHaveAttribute("autocomplete", "new-password")
        expect(input).toHaveAttribute("minlength", "15")
    })

    it("calls onChange with the new value", () => {
        const onChange = vi.fn()
        render(
            <PasswordField
                id="new-password"
                label="New password"
                value=""
                onChange={onChange}
                autoComplete="new-password"
            />,
        )

        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "correct-password-15-chars" },
        })
        expect(onChange).toHaveBeenCalledWith("correct-password-15-chars")
    })
})
