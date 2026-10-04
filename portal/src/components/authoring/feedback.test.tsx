import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { AuthoringError } from "../../types/apiError"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    LifecycleBadge,
    MutationStatusMessage,
    StaleWriteNotice,
} from "./feedback"

const error = (kind: AuthoringError["kind"], code: string | null = null): AuthoringError => ({
    kind,
    status: 0,
    code,
    correlationId: null,
})

describe("ErrorSummary", () => {
    it("renders nothing when there is nothing to say", () => {
        const { container } = render(<ErrorSummary errors={[]} attempt={3} />)
        expect(container).toBeEmptyDOMElement()
    })

    it("is one alert that takes focus on a failed attempt and links each error to its field", () => {
        render(
            <>
                <input id="world-name" aria-label="World name" />
                <ErrorSummary
                    errors={[{ fieldId: "world-name", message: "Name is required." }]}
                    attempt={1}
                />
            </>,
        )
        const alert = screen.getByRole("alert")
        expect(alert).toHaveFocus()
        expect(alert).toHaveTextContent("There is a problem")

        fireEvent.click(screen.getByRole("link", { name: "Name is required." }))
        expect(screen.getByLabelText("World name")).toHaveFocus()
    })

    it("does not steal focus before any attempt", () => {
        render(<ErrorSummary errors={[{ fieldId: "x", message: "m" }]} attempt={0} />)
        expect(screen.getByRole("alert")).not.toHaveFocus()
    })

    it("re-focuses on every further failed attempt", () => {
        const errors = [{ fieldId: "x", message: "m" }]
        const { rerender } = render(
            <>
                <button type="button">elsewhere</button>
                <ErrorSummary errors={errors} attempt={1} />
            </>,
        )
        screen.getByRole("button", { name: "elsewhere" }).focus()
        rerender(
            <>
                <button type="button">elsewhere</button>
                <ErrorSummary errors={errors} attempt={2} />
            </>,
        )
        expect(screen.getByRole("alert")).toHaveFocus()
    })
})

describe("FormActions", () => {
    it("offers explicit Save and Cancel; Cancel does not submit", () => {
        const onSubmit = vi.fn()
        const onCancel = vi.fn()
        render(
            <AuthoringForm label="Test" onSubmit={onSubmit}>
                <FormActions pending={false} onCancel={onCancel} />
            </AuthoringForm>,
        )
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(onCancel).toHaveBeenCalled()
        expect(onSubmit).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(onSubmit).toHaveBeenCalledTimes(1)
    })

    it("shows a busy, disabled Saving… state while pending", () => {
        render(<FormActions pending onCancel={() => {}} />)
        const save = screen.getByRole("button", { name: "Saving…" })
        expect(save).toBeDisabled()
        expect(save).toHaveAttribute("aria-busy", "true")
        expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
    })
})

describe("MutationStatusMessage", () => {
    const render1 = (e: AuthoringError, retry = vi.fn(), check = vi.fn()) =>
        render(<MutationStatusMessage error={e} onRetry={retry} onCheckSession={check} />)

    it("offers Retry for network and server failures and says input was kept", () => {
        const retry = vi.fn()
        render1(error("network"), retry)
        expect(screen.getByRole("alert")).toHaveTextContent(/input has been kept/)
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))
        expect(retry).toHaveBeenCalled()
    })

    it("shows the correlation id for a server failure only", () => {
        render1({ ...error("server"), correlationId: "abc-123" })
        expect(screen.getByText("Reference: abc-123")).toBeInTheDocument()
    })

    it("offers Check my session for a denied write", () => {
        const check = vi.fn()
        render1(error("denied"), vi.fn(), check)
        fireEvent.click(screen.getByRole("button", { name: "Check my session" }))
        expect(check).toHaveBeenCalled()
    })

    it("uses a specific sentence for a known domain code", () => {
        render1(error("conflict", "world_has_active_campaigns"))
        expect(screen.getByRole("alert")).toHaveTextContent("still has active campaigns")
    })

    it("explains an unavailable record without disclosing why", () => {
        render1(error("unavailable"))
        expect(screen.getByRole("alert")).toHaveTextContent(
            "no longer exists, or you can no longer access it",
        )
    })
})

describe("StaleWriteNotice", () => {
    it("loads the latest version on request and keeps the user's changes visible", () => {
        const onLoadLatest = vi.fn()
        render(
            <StaleWriteNotice
                onLoadLatest={onLoadLatest}
                yourChanges={<p>My unsaved name</p>}
            />,
        )
        expect(screen.getByRole("alert")).toHaveTextContent(/Someone else changed this record/)
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent(
            "My unsaved name",
        )
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        expect(onLoadLatest).toHaveBeenCalled()
    })
})

describe("LifecycleBadge", () => {
    it.each([
        ["draft", "Draft"],
        ["proposed", "In review"],
        ["approved", "Approved"],
        ["canon", "Canon"],
        ["superseded", "Superseded"],
        ["rejected", "Rejected"],
        ["archived", "Archived"],
    ])("labels %s as %s with text and a decorative icon", (status, label) => {
        const { container } = render(<LifecycleBadge status={status} />)
        expect(screen.getByText(label)).toBeInTheDocument()
        expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
    })

    it("falls back to the raw code for an unknown status", () => {
        render(<LifecycleBadge status="mystery" />)
        expect(screen.getByText("mystery")).toBeInTheDocument()
    })
})
