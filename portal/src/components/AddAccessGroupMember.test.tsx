import { act, fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AddAccessGroupMember } from "./AddAccessGroupMember"

const mockedHook = vi.hoisted(() => ({
    submit: vi.fn(),
    reset: vi.fn(),
    onSuccess: null as null | ((addedCount: number) => void),
}))

vi.mock("../hooks/useAddAccessGroupMember", () => ({
    useAddAccessGroupMember: (
        _campaignId: string,
        onSuccess: (addedCount: number) => void,
    ) => {
        mockedHook.onSuccess = onSuccess

        return {
            status: { kind: "idle" as const },
            submit: mockedHook.submit,
            reset: mockedHook.reset,
        }
    },
}))

const eligibleMembers = [
    {
        campaign_membership_id: "membership-alice",
        display_name: "Alice",
    },
    {
        campaign_membership_id: "membership-bob",
        display_name: "Bob",
    },
    {
        campaign_membership_id: "membership-charlie",
        display_name: "Charlie",
    },
]

function renderComponent() {
    const onChanged = vi.fn()
    const onMutationStart = vi.fn()

    render(
        <AddAccessGroupMember
            campaignId="campaign-1"
            accessGroupId="group-1"
            groupName="Test Group"
            eligibleMembers={eligibleMembers}
            onChanged={onChanged}
            onMutationStart={onMutationStart}
        />,
    )

    return {
        onChanged,
        onMutationStart,
    }
}

describe("AddAccessGroupMember", () => {
    beforeEach(() => {
        mockedHook.submit.mockReset()
        mockedHook.reset.mockReset()
        mockedHook.onSuccess = null
    })

    it("submits all selected members in one operation", () => {
        const { onMutationStart } = renderComponent()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add members",
            }),
        )

        const alice = screen.getByRole("checkbox", {
            name: "Alice",
        })
        const bob = screen.getByRole("checkbox", {
            name: "Bob",
        })
        const addButton = screen.getByRole("button", {
            name: "Add selected members",
        })

        expect(alice).not.toBeChecked()
        expect(bob).not.toBeChecked()
        expect(addButton).toBeDisabled()
        expect(
            screen.getByText("No members selected."),
        ).toBeInTheDocument()

        fireEvent.click(alice)
        fireEvent.click(bob)

        expect(alice).toBeChecked()
        expect(bob).toBeChecked()
        expect(
            screen.getByText("2 members selected."),
        ).toBeInTheDocument()
        expect(addButton).toBeEnabled()

        fireEvent.click(addButton)

        expect(onMutationStart).toHaveBeenCalledOnce()
        expect(mockedHook.submit).toHaveBeenCalledWith("group-1", [
            "membership-alice",
            "membership-bob",
        ])
    })

    it("clears the selection when editing is cancelled", () => {
        renderComponent()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add members",
            }),
        )

        fireEvent.click(
            screen.getByRole("checkbox", {
                name: "Charlie",
            }),
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Cancel",
            }),
        )

        expect(mockedHook.submit).not.toHaveBeenCalled()
        expect(
            screen.queryByRole("checkbox", {
                name: "Charlie",
            }),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add members",
            }),
        )

        expect(
            screen.getByRole("checkbox", {
                name: "Charlie",
            }),
        ).not.toBeChecked()
    })

    it("reports the authoritative number of members added", () => {
        const { onChanged } = renderComponent()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add members",
            }),
        )

        const success = mockedHook.onSuccess

        expect(success).not.toBeNull()

        act(() => {
            success?.(2)
        })

        expect(onChanged).toHaveBeenCalledWith(
            "2 members added to group.",
        )
        expect(
            screen.getByRole("button", {
                name: "Add members",
            }),
        ).toBeInTheDocument()
    })
})