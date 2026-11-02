export interface Recovery {
    to: string
    label: string
}

// Where a person who is stopped can always go: the portal home.
export const HOME_RECOVERY: Recovery = { to: "/", label: "Go to the portal home" }
