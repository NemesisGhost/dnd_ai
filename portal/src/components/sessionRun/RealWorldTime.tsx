function formatRealWorld(value: string): string {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

// A real-world timestamp, labelled as such so it is never read as in-world time.
export function RealWorldTime({ label, value }: { label: string; value: string }) {
    return (
        <>
            {label}: <time dateTime={value}>{formatRealWorld(value)}</time>
        </>
    )
}
