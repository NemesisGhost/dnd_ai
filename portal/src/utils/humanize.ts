// Turns an underscore_separated database code into a human-readable label
// at the presentation boundary (UI_STYLE_GUIDE.md §15).
export function humanizeCode(code: string): string {
    return code
        .split("_")
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ")
}
