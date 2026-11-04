import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react"
import type {
    FocusEvent as ReactFocusEvent,
    KeyboardEvent as ReactKeyboardEvent,
    MouseEvent as ReactMouseEvent,
    RefObject,
} from "react"
import { UNSAFE_DataRouterContext, parsePath, useLocation, useNavigationType } from "react-router"
import { navigationQuestionActive, onQuestionAnswer, registerFocusFallback } from "../hooks/navigationHolds"
import { NavigationAttempt, hrefOf, isBusy, viewOfRouterState } from "../navigation/navigationAttempt"
import type { AttemptView } from "../navigation/navigationAttempt"
import { recordActivation, releaseActivation } from "../navigation/activationOwner"
import { canTakeFocus } from "../utils/focusEligibility"

// The one open / close / focus lifecycle of every sidebar menu and of the drawer (docs/UI_DESIGN.md §4,
// plan §6.4). Pointer and keyboard follow the same rules; nothing here navigates, disposes input or
// changes the selection by itself.

// What can take focus inside a menu: a link or an enabled button. A DisabledNavItem is neither.
const MENU_ITEM = "a[href], button:not(:disabled)"
// A control that opens or closes the menu (the main control and the disclosure).
export const MENU_CONTROL_ATTRIBUTE = "data-menu-control"

// Distance order of the fallbacks a Stay may use, nearest first (ConfirmDialog tries them in this order).
const FALLBACK_ACTIVATED = 0
const FALLBACK_OPENER = 1
export const FALLBACK_DRAWER_TOGGLE = 2

// A click the browser handles itself (new tab, new window, download): not a navigation of this document.
function handledByBrowser(event: ReactMouseEvent<HTMLElement>): boolean {
    return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
}

interface Pending {
    attempt: NavigationAttempt
    release: () => void
}

interface AcceptedNavigationOptions {
    // Runs once, when the navigation the click itself started has arrived.
    onAccepted: () => void
    // The control Stay falls back to when the activated one is no longer usable, after the activated one.
    opener: () => HTMLElement | null
}

export interface AcceptedNavigation {
    // Called from a navigation control's onClick, before the router handles it. Records what was asked for
    // and nothing else: the menu and the drawer stay as they are until the location changes.
    begin: (event: ReactMouseEvent<HTMLElement>, to: string) => void
    // Forgets a recorded click (the person moved on).
    cancel: () => void
}

/**
 * Closing on *accepted* navigation (CTX-4). A click records the full destination (path, query and hash)
 * and the entry it left, and then watches the router for the request it started: held by the
 * unsaved-changes question, in flight, redirected, or committed (`navigation/navigationAttempt.ts` states
 * the contract). Only that request arriving closes the menu and the drawer, once. Stay, a failed route, a
 * superseding or unrelated navigation (Back, a REPLACE, another link, the same address asked for by
 * someone else), and the stamp-only replacements the selected-context owners write never complete it, and
 * leave nothing pending. Without a data router (an isolated test) only commits can be watched, and the
 * same rules apply to them.
 */
export function useAcceptedNavigation({ onAccepted, opener }: AcceptedNavigationOptions): AcceptedNavigation {
    const location = useLocation()
    const navigationType = useNavigationType()
    const router = useContext(UNSAFE_DataRouterContext)?.router ?? null
    const pending = useRef<Pending | null>(null)
    const accepted = useRef(onAccepted)
    const openerRef = useRef(opener)
    useLayoutEffect(() => {
        accepted.current = onAccepted
        openerRef.current = opener
    })

    const cancel = useCallback(() => {
        pending.current?.release()
        pending.current = null
    }, [])

    useEffect(() => cancel, [cancel])

    // Stay is the person's answer, reported by the blocker that asked. Leave needs nothing here: the
    // location reaching the requested path is what completes the click.
    useEffect(
        () =>
            onQuestionAnswer((answer) => {
                if (answer === "stay") cancel()
            }),
        [cancel],
    )

    // Feeds the attempt a view of the router; settles it when it has an answer.
    const feed = useCallback(
        (view: AttemptView) => {
            const current = pending.current
            if (current === null) return
            const status = current.attempt.observe(view)
            if (status === "pending") return
            cancel()
            if (status === "accepted") accepted.current()
        },
        [cancel],
    )

    const begin = useCallback(
        (event: ReactMouseEvent<HTMLElement>, to: string) => {
            if (event.defaultPrevented || handledByBrowser(event)) return
            cancel()
            const activated = event.currentTarget
            const left = router?.state.location ?? location
            const releases = [
                registerFocusFallback(FALLBACK_ACTIVATED, () => activated),
                registerFocusFallback(FALLBACK_OPENER, () => openerRef.current()),
            ]
            // The router tells us everything from here on, in order; the click's own navigate() call follows
            // this handler, so its first notification is the first thing we see of it.
            if (router !== null) releases.push(router.subscribe((state) => feed(viewOfRouterState(state))))
            const target = parsePath(to)
            recordActivation(activated, target.pathname ?? "")
            releases.push(() => releaseActivation(activated))
            pending.current = {
                attempt: new NavigationAttempt(
                    { pathname: target.pathname ?? "", search: target.search ?? "", hash: target.hash ?? "" },
                    { key: left.key, href: hrefOf(left) },
                    router !== null && isBusy(router.state),
                ),
                release: () => releases.forEach((release) => release()),
            }
        },
        [cancel, feed, location, router],
    )

    // Without a data router there is nothing to watch but commits.
    useEffect(() => {
        if (router !== null || pending.current === null) return
        feed({
            location,
            action: navigationType,
            navigating: null,
            blocked: null,
            proceeding: null,
            failed: false,
            busy: false,
        })
    }, [feed, location, navigationType, router])

    return { begin, cancel }
}

interface SidebarMenuOptions {
    initialOpen: boolean
    // Closes the drawer (narrow viewport); called when a navigation made from the menu is accepted.
    onNavigate: () => void
}

// What a group renders from. Holds no ref (the refs are returned beside it), so a render can read it freely.
export interface SidebarMenu {
    open: boolean
    // The main control or the disclosure was activated: toggle, recording it as the opener.
    toggleFrom: (opener: HTMLElement) => void
    // For the group's <li>.
    onKeyDown: (event: ReactKeyboardEvent<HTMLLIElement>) => void
    onBlur: (event: ReactFocusEvent<HTMLLIElement>) => void
    // For each child link's onClick.
    onItemClick: (to: string) => (event: ReactMouseEvent<HTMLElement>) => void
}

function firstControl(container: HTMLElement | null): HTMLElement | null {
    return container?.querySelector<HTMLElement>(`[${MENU_CONTROL_ATTRIBUTE}]`) ?? null
}

export function useSidebarMenu({
    initialOpen,
    onNavigate,
}: SidebarMenuOptions): {
    menu: SidebarMenu
    containerRef: RefObject<HTMLLIElement | null>
    submenuRef: RefObject<HTMLUListElement | null>
} {
    // Whether the route is inside the section is read once, on mount: choosing a child (which navigates)
    // must not be undone by the route becoming active underneath it.
    const [open, setOpen] = useState(initialOpen)
    const containerRef = useRef<HTMLLIElement>(null)
    const submenuRef = useRef<HTMLUListElement>(null)
    // The control the person opened the menu with. Escape returns here.
    const openerRef = useRef<HTMLElement | null>(null)
    // Focus moves into the menu only when the person opens it, never when it starts open for the route:
    // otherwise every remount of the persistent sidebar would steal focus.
    const focusFirstRef = useRef(false)

    const usableOpener = useCallback((): HTMLElement | null => {
        const recorded = openerRef.current
        if (canTakeFocus(recorded)) return recorded
        const first = firstControl(containerRef.current)
        return canTakeFocus(first) ? first : null
    }, [])

    const navigation = useAcceptedNavigation({
        onAccepted: () => {
            setOpen(false)
            onNavigate()
        },
        opener: usableOpener,
    })

    useEffect(() => {
        if (!open || !focusFirstRef.current) return
        focusFirstRef.current = false
        submenuRef.current?.querySelector<HTMLElement>(MENU_ITEM)?.focus()
    }, [open])

    useEffect(() => {
        if (!open) return

        function handlePointerDown(event: PointerEvent): void {
            // The question owns the screen: a press outside the menu (inside its dialog, say) is not a dismissal.
            if (navigationQuestionActive()) return
            const target = event.target as Node | null
            if (target !== null && containerRef.current?.contains(target)) return
            // Outside dismissal never moves focus, so an outside control the person pressed keeps it.
            setOpen(false)
        }

        document.addEventListener("pointerdown", handlePointerDown)
        return () => {
            document.removeEventListener("pointerdown", handlePointerDown)
        }
    }, [open])

    const toggleFrom = useCallback(
        (opener: HTMLElement) => {
            if (open) {
                navigation.cancel()
                setOpen(false)
                return
            }
            openerRef.current = opener
            focusFirstRef.current = true
            setOpen(true)
        },
        [navigation, open],
    )

    function onKeyDown(event: ReactKeyboardEvent<HTMLLIElement>): void {
        if (event.key !== "Escape" || !open) return
        // Handled here, not globally, so it cannot also close the drawer.
        event.stopPropagation()
        navigation.cancel()
        setOpen(false)
        usableOpener()?.focus()
    }

    function onBlur(event: ReactFocusEvent<HTMLLIElement>): void {
        if (!open || navigationQuestionActive()) return
        const next = event.relatedTarget as Node | null
        if (next !== null && containerRef.current?.contains(next)) return
        setOpen(false)
    }

    const onItemClick = (to: string) => (event: ReactMouseEvent<HTMLElement>) => {
        navigation.begin(event, to)
    }

    return { menu: { open, toggleFrom, onKeyDown, onBlur, onItemClick }, containerRef, submenuRef }
}
