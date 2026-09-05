import type { ReactNode } from "react"
import { useState } from "react"
import type { SortDirection } from "../utils/sorting"

export interface SortableTableColumn<T> {
    key: string
    label: string
    render: (row: T) => ReactNode
    /** Receives the current sort direction so a column can encode
     * direction-dependent placement (e.g. nulls always last) instead of
     * relying on a generic whole-array reversal — see
     * `compareNullableTimestamps`/`applyDirection` in `utils/sorting`. */
    compare?: (a: T, b: T, direction: SortDirection) => number
}

interface SortState {
    column: string
    direction: SortDirection
}

interface SortableTableProps<T> {
    columns: SortableTableColumn<T>[]
    rows: T[]
    getRowKey: (row: T) => string
    initialSort?: SortState
    caption: string
}

export function SortableTable<T>({
    columns,
    rows,
    getRowKey,
    initialSort,
    caption,
}: SortableTableProps<T>) {
    const [sort, setSort] = useState<SortState | null>(
        initialSort ?? null,
    )

    function handleSort(column: SortableTableColumn<T>) {
        if (column.compare === undefined) {
            return
        }
        setSort((current) =>
            current?.column === column.key
                ? {
                      column: column.key,
                      direction: current.direction === "asc" ? "desc" : "asc",
                  }
                : { column: column.key, direction: "asc" },
        )
    }

    const activeColumn =
        sort !== null
            ? columns.find((column) => column.key === sort.column)
            : undefined

    const sortedRows = (() => {
        const compare = activeColumn?.compare
        if (sort === null || compare === undefined) {
            return rows
        }
        return [...rows].sort((a, b) => compare(a, b, sort.direction))
    })()

    return (
        <table className="sortable-table">
            <caption>{caption}</caption>
            <thead>
                <tr>
                    {columns.map((column) => {
                        const isSortable = column.compare !== undefined
                        const isSorted = sort?.column === column.key
                        const ariaSort =
                            isSortable && isSorted
                                ? sort.direction === "asc"
                                    ? "ascending"
                                    : "descending"
                                : undefined

                        return (
                            <th
                                key={column.key}
                                scope="col"
                                aria-sort={ariaSort}
                            >
                                {isSortable ? (
                                    <button
                                        type="button"
                                        className="sortable-table__sort-button"
                                        onClick={() => handleSort(column)}
                                    >
                                        {column.label}
                                        {isSorted && (
                                            <span aria-hidden="true">
                                                {sort.direction === "asc" ? " ▲" : " ▼"}
                                            </span>
                                        )}
                                    </button>
                                ) : (
                                    column.label
                                )}
                            </th>
                        )
                    })}
                </tr>
            </thead>
            <tbody>
                {sortedRows.map((row) => (
                    <tr key={getRowKey(row)}>
                        {columns.map((column) => (
                            <td key={column.key}>{column.render(row)}</td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}
