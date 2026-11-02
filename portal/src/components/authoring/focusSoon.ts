// Moves keyboard focus to an element by id once it exists (after a form opens or closes).
export function focusSoon(id: string): void {
    requestAnimationFrame(() => document.getElementById(id)?.focus())
}
