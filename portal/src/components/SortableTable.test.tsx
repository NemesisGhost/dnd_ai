import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
} from "vitest"
import type { SortableTableColumn } from "./SortableTable"
import { SortableTable } from "./SortableTable"
import {
    applyDirection,
    compareNullableTimestamps,
} from "../utils/sorting"

interface Row {
    id: string
    name: string
}

const rows: Row[] = [
    { id: "b", name: "Bravo" },
    { id: "a", name: "Alpha" },
    { id: "c", name: "Charlie" },
]

const sortableColumns: SortableTableColumn<Row>[] = [
    {
        key: "name",
        label: "Name",
        compare: (a, b, direction) =>
            applyDirection(direction, a.name.localeCompare(b.name)),
        render: (row) => row.name,
    },
]

function namesInOrder(): string[] {
    return screen.getAllByRole("row").slice(1).map((row) => row.textContent)
}

describe("SortableTable", () => {
    it("uses the caption prop as the table's accessible name", () => {
        render(
            <SortableTable
                caption="Test table"
                columns={sortableColumns}
                rows={rows}
                getRowKey={(row) => row.id}
            />,
        )

        expect(
            screen.getByRole("table", { name: "Test table" }),
        ).toBeInTheDocument()
    })

    it("renders a visible <caption> element with the caption text", () => {
        const { container } = render(
            <SortableTable
                caption="Test table"
                columns={sortableColumns}
                rows={rows}
                getRowKey={(row) => row.id}
            />,
        )

        expect(container.querySelector("caption")).toHaveTextContent(
            "Test table",
        )
    })

    it("renders column headers and row cells via the supplied render callbacks", () => {
        render(
            <SortableTable
                caption="Test table"
                columns={sortableColumns}
                rows={rows}
                getRowKey={(row) => row.id}
            />,
        )

        expect(
            screen.getByRole("columnheader", { name: "Name" }),
        ).toBeInTheDocument()
        expect(namesInOrder()).toEqual(["Bravo", "Alpha", "Charlie"])
    })

    it("sorts ascending on first click and descending on a second click of the same column", () => {
        render(
            <SortableTable
                caption="Test table"
                columns={sortableColumns}
                rows={rows}
                getRowKey={(row) => row.id}
            />,
        )

        const header = screen.getByRole("columnheader", { name: "Name" })
        expect(header).not.toHaveAttribute("aria-sort")

        const button = screen.getByRole("button")
        fireEvent.click(button)
        expect(header).toHaveAttribute("aria-sort", "ascending")
        expect(namesInOrder()).toEqual(["Alpha", "Bravo", "Charlie"])

        fireEvent.click(button)
        expect(header).toHaveAttribute("aria-sort", "descending")
        expect(namesInOrder()).toEqual(["Charlie", "Bravo", "Alpha"])
    })

    it("honors initialSort without requiring a click", () => {
        render(
            <SortableTable
                caption="Test table"
                columns={sortableColumns}
                rows={rows}
                getRowKey={(row) => row.id}
                initialSort={{ column: "name", direction: "asc" }}
            />,
        )

        expect(
            screen.getByRole("columnheader", { name: "Name" }),
        ).toHaveAttribute("aria-sort", "ascending")
        expect(namesInOrder()).toEqual(["Alpha", "Bravo", "Charlie"])
    })

    it("only puts aria-sort on the currently sorted column, not on other sortable columns", () => {
        const columns: SortableTableColumn<Row>[] = [
            {
                key: "name",
                label: "Name",
                compare: (a, b, direction) =>
                    applyDirection(direction, a.name.localeCompare(b.name)),
                render: (row) => row.name,
            },
            {
                key: "id",
                label: "Id",
                compare: (a, b, direction) =>
                    applyDirection(direction, a.id.localeCompare(b.id)),
                render: (row) => row.id,
            },
        ]

        render(
            <SortableTable
                caption="Test table"
                columns={columns}
                rows={rows}
                getRowKey={(row) => row.id}
                initialSort={{ column: "name", direction: "asc" }}
            />,
        )

        expect(
            screen.getByRole("columnheader", { name: "Name" }),
        ).toHaveAttribute("aria-sort", "ascending")
        expect(
            screen.getByRole("columnheader", { name: "Id" }),
        ).not.toHaveAttribute("aria-sort")
    })

    it("renders a non-sortable column as plain text with no button or aria-sort", () => {
        const columns: SortableTableColumn<Row>[] = [
            { key: "name", label: "Name", render: (row) => row.name },
        ]

        render(
            <SortableTable
                caption="Test table"
                columns={columns}
                rows={rows}
                getRowKey={(row) => row.id}
            />,
        )

        const header = screen.getByRole("columnheader", { name: "Name" })
        expect(header).not.toHaveAttribute("aria-sort")
        expect(
            screen.queryByRole("button"),
        ).not.toBeInTheDocument()
    })
})

interface TimedRow {
    id: string
    at: string | null
}

const timedRows: TimedRow[] = [
    { id: "1", at: "2026-01-02T00:00:00Z" },
    { id: "2", at: null },
    { id: "3", at: "2026-01-01T00:00:00Z" },
]

const timedColumns: SortableTableColumn<TimedRow>[] = [
    {
        key: "at",
        label: "At",
        compare: (a, b, direction) =>
            compareNullableTimestamps(a.at, b.at, direction),
        render: (row) => row.at ?? "Not recorded",
    },
]

function atCellsInOrder(): string[] {
    return screen.getAllByRole("row").slice(1).map((row) => row.textContent)
}

describe("SortableTable with a nullable date column", () => {
    it("keeps a null row last whether sorted ascending or descending", () => {
        render(
            <SortableTable
                caption="Timed rows"
                columns={timedColumns}
                rows={timedRows}
                getRowKey={(row) => row.id}
                initialSort={{ column: "at", direction: "asc" }}
            />,
        )

        expect(atCellsInOrder()).toEqual([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "Not recorded",
        ])

        fireEvent.click(screen.getByRole("button", { name: "At" }))

        expect(atCellsInOrder()).toEqual([
            "2026-01-02T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "Not recorded",
        ])
    })
})
