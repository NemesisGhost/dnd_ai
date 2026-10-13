import { useUnsavedChangesGuard } from "../../hooks/useUnsavedChangesGuard"
import { ConfirmDialog } from "../authoring/ConfirmDialog"

// One guard for everything an editor has typed and not yet sent into a staged workspace (a hand-over,
// a place, an amount, a source): leaving the page asks first, and so does closing the tab
// (docs/UI_DESIGN.md §5.11). `unsaved` names what would be lost.
export function UnsavedInputGuard({ unsaved }: { unsaved: string[] }) {
    const guard = useUnsavedChangesGuard(unsaved.length > 0)
    return (
        <ConfirmDialog
            open={guard.blocked}
            title="Discard unsaved input?"
            description={`You have entered ${unsaved.join(" and ")}. It has not been sent.`}
            confirmLabel="Discard"
            cancelLabel="Keep editing"
            onConfirm={guard.discard}
            onCancel={guard.stay}
        />
    )
}
