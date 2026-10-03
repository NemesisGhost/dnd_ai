import {
    useEffect,
    useId,
    useRef,
    useState,
} from "react"
import type { FocusEvent, KeyboardEvent } from "react"
import { Link } from "react-router"
import { useSession } from "../context/SessionContext"
import { useLogout } from "../hooks/useLogout"
import { deriveProfileAvatar } from "../utils/profileIdentity"
import { ProfileAvatar } from "./ProfileAvatar"

// The profile button and its popup (UI_DESIGN §4.3). A disclosure
// (button + aria-expanded + aria-controls), deliberately not an ARIA
// menu — the identity summary and Administration label are plain text,
// which role="menu" would not allow as children, and Links/the Log out
// button keep their native roles.
export function ProfileMenu() {
    const { state } = useSession()
    const { status, logout } = useLogout()
    const [open, setOpen] = useState(false)

    const containerRef = useRef<HTMLDivElement>(null)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const firstItemRef = useRef<HTMLAnchorElement>(null)

    const menuId = useId()
    const adminLabelId = useId()

    const isAuthenticated = state.status === "authenticated"

    useEffect(() => {
        if (open) {
            firstItemRef.current?.focus()
        }
    }, [open])

    useEffect(() => {
        if (!open) {
            return
        }

        function handlePointerDown(event: PointerEvent): void {
            const target = event.target as Node | null

            if (
                target !== null &&
                containerRef.current?.contains(target)
            ) {
                return
            }

            // Outside dismissal never moves focus, so an outside control
            // the user activated keeps it.
            setOpen(false)
        }

        document.addEventListener("pointerdown", handlePointerDown)

        return () => {
            document.removeEventListener("pointerdown", handlePointerDown)
        }
    }, [open])

    if (!isAuthenticated) {
        return null
    }

    const { bootstrap } = state
    const displayName = bootstrap.user.display_name
    const usableName = displayName.trim().length > 0
    const avatar = deriveProfileAvatar({ displayName })
    const isPlatformAdministrator = bootstrap.is_platform_administrator

    function closeAndFocusButton(): void {
        setOpen(false)
        buttonRef.current?.focus()
    }

    function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
        if (event.key === "Escape" && open) {
            // Handled here, not globally, so it cannot fight
            // the sidebar drawer's own document-level Escape handler.
            event.stopPropagation()
            closeAndFocusButton()
        }
    }

    function handleBlur(event: FocusEvent<HTMLDivElement>): void {
        if (!open) {
            return
        }

        const next = event.relatedTarget as Node | null

        if (next !== null && containerRef.current?.contains(next)) {
            return
        }

        // Tabbing past the last item, or Shift+Tab back out before the
        // button, closes the menu without moving focus — whatever the
        // browser's own default tab movement already did stays as-is.
        setOpen(false)
    }

    function handleItemActivated(): void {
        // Close the menu, then let the router navigate. There is no
        // route-focus convention yet, so focus falls to the default
        // (body) — a deliberate, documented gap (navigation plan D-4).
        setOpen(false)
    }

    return (
        <div
            className="profile-menu"
            ref={containerRef}
            onKeyDown={handleKeyDown}
            onBlur={handleBlur}
        >
            <button
                ref={buttonRef}
                type="button"
                className="profile-menu__button"
                aria-expanded={open}
                aria-controls={menuId}
                aria-label={
                    usableName
                        ? `Account menu for ${displayName}`
                        : "Account menu"
                }
                onClick={() => setOpen((current) => !current)}
            >
                <ProfileAvatar model={avatar} />

                {usableName && (
                    <span
                        className="profile-menu__name"
                        aria-hidden="true"
                    >
                        {displayName}
                    </span>
                )}
            </button>

            <div
                id={menuId}
                className="profile-menu__popup"
                hidden={!open}
            >
                {usableName && (
                    <p className="profile-menu__identity">
                        Signed in as <strong>{displayName}</strong>
                    </p>
                )}

                <ul aria-label="Account" className="profile-menu__list">
                    <li>
                        <Link
                            ref={firstItemRef}
                            to="/settings"
                            onClick={handleItemActivated}
                        >
                            Settings
                        </Link>
                    </li>
                    <li>
                        <Link to="/account" onClick={handleItemActivated}>
                            Account &amp; Security
                        </Link>
                    </li>
                </ul>

                {isPlatformAdministrator && (
                    <div
                        role="group"
                        aria-labelledby={adminLabelId}
                        className="profile-menu__group"
                    >
                        <p
                            id={adminLabelId}
                            className="profile-menu__section-label"
                        >
                            Administration
                        </p>

                        <ul className="profile-menu__list">
                            <li>
                                <Link
                                    to="/platform/accounts"
                                    onClick={handleItemActivated}
                                >
                                    Platform Accounts
                                </Link>
                            </li>
                        </ul>
                    </div>
                )}

                <hr />

                <button
                    type="button"
                    className="profile-menu__logout"
                    onClick={() => void logout()}
                    disabled={status.kind === "pending"}
                    aria-busy={status.kind === "pending"}
                >
                    {status.kind === "pending" ? "Logging out…" : "Log out"}
                </button>

                {status.kind === "error" && (
                    <p role="alert" className="profile-menu__error">
                        {status.message}
                    </p>
                )}
            </div>
        </div>
    )
}
