import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { OneTimeSecretPanel } from "./OneTimeSecretPanel"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("OneTimeSecretPanel", () => {
    it("shows the secret as read-only text and copies it on request", async () => {
        const clipboardWriteText = vi.fn().mockResolvedValue(undefined)
        vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWriteText } })

        render(
            <OneTimeSecretPanel
                heading="Copy the link now"
                description="Shown once."
                secretLabel="Activation link"
                secret="https://example.test/auth/activate#token=abc"
                onDismiss={vi.fn()}
            />,
        )

        const input = screen.getByLabelText("Activation link")
        expect(input).toHaveAttribute("readonly")
        expect(input).toHaveValue("https://example.test/auth/activate#token=abc")

        fireEvent.click(screen.getByRole("button", { name: "Copy" }))
        await vi.waitFor(() => {
            expect(clipboardWriteText).toHaveBeenCalledWith(
                "https://example.test/auth/activate#token=abc",
            )
        })
    })

    it("calls onDismiss when dismissed", () => {
        const onDismiss = vi.fn()
        render(
            <OneTimeSecretPanel
                heading="Copy the link now"
                description="Shown once."
                secretLabel="Activation link"
                secret="secret-value"
                onDismiss={onDismiss}
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
        expect(onDismiss).toHaveBeenCalledTimes(1)
    })
})
