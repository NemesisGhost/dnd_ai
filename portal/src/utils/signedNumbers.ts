function formatSignedNumber(
    value: number | null,
): string {
    if (value === null) {
        return "Not available"
    }

    if (value > 0) {
        return `+${value}`
    }

    return String(value)
}

export default formatSignedNumber