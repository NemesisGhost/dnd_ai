import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StrictMode, useEffect } from "react"
import { MemoryRouter, useNavigate } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { ThemeProvider } from "./themes/ThemeProvider"

// Route-level integration test for the invitation continuation. Mounts the
// real <App /> under the real RouteSessionProvider and router, and fakes only
// the network edge (`fetch`) with a small stateful server that models the
// two cookies (browser session, onboarding continuation) the way the real
// API does. Nothing in the portal's hooks, pages, or session plumbing is
// mocked, so the navigation/provider lifetime that deployed users hit is the
// thing under test -- including the begin-vs-status request race that a
// mocked-hook test cannot express.

const RAW_TOKEN = "raw-invitation-token-DO-NOT-LEAK"
const CAMPAIGN_NAME = "Fixture Campaign"
const ONBOARDING_CSRF = "onboarding-csrf-fixture"
const PASSWORD = "correct horse battery staple"

interface Account {
    userId: string
    displayName: string
}

interface RecordedRequest {
    method: string
    path: string
    body: string | null
    signal: AbortSignal | null
}

class FakeServer {
    accounts = new Map<string, Account & { password: string }>([
        ["existing", { userId: "u-existing", displayName: "Existing User", password: PASSWORD }],
        ["other", { userId: "u-other", displayName: "Other User", password: PASSWORD }],
    ])
    sessionUser: Account | null = null
    sessionCsrf = "session-csrf-fixture"
    onboardingLive = false
    invitationValid = true
    members = new Set<string>()
    completeCount = 0
    requests: RecordedRequest[] = []
    // When set, `start` does not respond until released, so a test can let
    // other requests (e.g. a premature status read) overtake it.
    startGate: Promise<void> | null = null
    completeGate: Promise<void> | null = null

    private json(status: number, body: unknown): Response {
        return new Response(body === null ? null : JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
        })
    }

    private onboardingBody() {
        return {
            campaign_display_name: CAMPAIGN_NAME,
            invitation_expires_at: "2099-01-01T00:00:00Z",
            onboarding_expires_at: "2099-01-01T00:00:00Z",
            onboarding_csrf_token: ONBOARDING_CSRF,
            next_action: this.sessionUser === null ? "sign_in_or_register" : "confirm",
            signed_in_display_name: this.sessionUser?.displayName ?? null,
        }
    }

    private bootstrap() {
        const user = this.sessionUser!
        return {
            ...sessionBootstrapFixture,
            user: { user_id: user.userId, display_name: user.displayName },
            csrf_token: this.sessionCsrf,
            campaigns: this.members.has(user.userId) ? sessionBootstrapFixture.campaigns : [],
        }
    }

    expireInvitation(): void {
        this.invitationValid = false
        this.onboardingLive = false
    }

    async handle(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
        const path = String(input)
        const method = init?.method ?? "GET"
        const headers = new Headers(init?.headers)
        const body = typeof init?.body === "string" ? init.body : null
        this.requests.push({ method, path, body, signal: init?.signal ?? null })
        const key = `${method} ${path}`

        switch (key) {
            case "GET /auth/session":
                return this.sessionUser === null
                    ? this.json(401, { error: "unauthenticated" })
                    : this.json(200, this.bootstrap())

            case "POST /auth/login": {
                const credentials = JSON.parse(body ?? "{}") as {
                    login_name: string
                    password: string
                }
                const account = this.accounts.get(credentials.login_name)
                if (account === undefined || account.password !== credentials.password) {
                    return this.json(401, { error: "bad credentials" })
                }
                this.sessionUser = account
                return this.json(200, { user_id: account.userId, csrf_token: this.sessionCsrf })
            }

            case "POST /auth/logout":
                this.sessionUser = null
                return new Response(null, { status: 204 })

            case "POST /api/campaign-invitations/onboarding/start": {
                if (this.startGate !== null) {
                    await this.startGate
                }
                const sent = JSON.parse(body ?? "{}") as { token: string }
                if (!this.invitationValid || sent.token !== RAW_TOKEN) {
                    return this.json(404, { error: "unavailable" })
                }
                this.onboardingLive = true
                return this.json(201, this.onboardingBody())
            }

            case "GET /api/campaign-invitations/onboarding/status":
                return this.onboardingLive
                    ? this.json(200, this.onboardingBody())
                    : this.json(404, { error: "unavailable" })

            case "POST /api/campaign-invitations/onboarding/complete": {
                if (this.completeGate !== null) {
                    await this.completeGate
                }
                if (this.sessionUser === null || headers.get("X-CSRF-Token") !== this.sessionCsrf) {
                    return this.json(401, { error: "unauthenticated" })
                }
                if (!this.onboardingLive || !this.invitationValid) {
                    return this.json(404, { error: "unavailable" })
                }
                this.completeCount += 1
                this.members.add(this.sessionUser.userId)
                this.onboardingLive = false
                return this.json(200, { campaign_display_name: CAMPAIGN_NAME })
            }

            case "POST /api/campaign-invitations/onboarding/cancel":
                if (!this.onboardingLive) {
                    return this.json(404, { error: "unavailable" })
                }
                if (headers.get("X-Onboarding-CSRF-Token") !== ONBOARDING_CSRF) {
                    return this.json(403, { error: "forbidden" })
                }
                this.onboardingLive = false
                return new Response(null, { status: 204 })

            case "POST /api/campaign-invitations/onboarding/register": {
                if (!this.onboardingLive) {
                    return this.json(404, { error: "unavailable" })
                }
                const registration = JSON.parse(body ?? "{}") as {
                    login_name: string
                    display_name: string
                }
                const account = {
                    userId: `u-${registration.login_name}`,
                    displayName: registration.display_name,
                }
                this.sessionUser = account
                this.members.add(account.userId)
                this.onboardingLive = false
                return this.json(201, {
                    csrf_token: this.sessionCsrf,
                    campaign_display_name: CAMPAIGN_NAME,
                })
            }
        }

        return this.json(500, { error: `unexpected request ${key}` })
    }

    count(method: string, path: string): number {
        return this.requests.filter((r) => r.method === method && r.path === path).length
    }
}

let server: FakeServer
const navigation: { go: (to: string | number) => void } = {
    go: () => {
        throw new Error("NavigationProbe is not mounted")
    },
}

function navigateExternally(to: string | number): void {
    navigation.go(to)
}

function NavigationProbe() {
    const navigate = useNavigate()
    useEffect(() => {
        navigation.go = (to) => {
            act(() => {
                if (typeof to === "number") {
                    void navigate(to)
                } else {
                    void navigate(to)
                }
            })
        }
    }, [navigate])
    return null
}

function openInvitationLink(token: string = RAW_TOKEN, strict = false) {
    // The real page reads the fragment from window.location, not the router.
    window.history.replaceState(null, "", `/campaign-invitations/accept#token=${token}`)
    const tree = (
        <ThemeProvider>
            <MemoryRouter initialEntries={["/campaign-invitations/accept"]}>
                <NavigationProbe />
                <RouteSessionProvider>
                    <App />
                </RouteSessionProvider>
            </MemoryRouter>
        </ThemeProvider>
    )
    return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function openPlainLogin() {
    window.history.replaceState(null, "", "/login")
    return render(
        <ThemeProvider>
            <MemoryRouter initialEntries={["/login"]}>
                <NavigationProbe />
                <RouteSessionProvider>
                    <App />
                </RouteSessionProvider>
            </MemoryRouter>
        </ThemeProvider>,
    )
}

async function signInInline(loginName: string, password: string) {
    const form = await screen.findByRole("form", { name: "Sign in to your account" })
    fireEvent.change(within(form).getByLabelText("Login name"), { target: { value: loginName } })
    fireEvent.change(within(form).getByLabelText("Password"), { target: { value: password } })
    fireEvent.click(within(form).getByRole("button", { name: "Sign in" }))
}

async function signInOnLoginPage(loginName: string, password: string) {
    fireEvent.change(await screen.findByLabelText("Email or Username"), {
        target: { value: loginName },
    })
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } })
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }))
}

function expectNoTokenAnywhere() {
    expect(window.location.href).not.toContain(RAW_TOKEN)
    expect(window.location.hash).toBe("")
    expect(JSON.stringify(window.history.state)).not.toContain(RAW_TOKEN)
    // The theme provider legitimately stores a theme choice; what must never
    // appear in any browser storage is the invitation token.
    for (const storage of [window.localStorage, window.sessionStorage]) {
        for (let index = 0; index < storage.length; index += 1) {
            const key = storage.key(index)!
            expect(key).not.toContain(RAW_TOKEN)
            expect(storage.getItem(key) ?? "").not.toContain(RAW_TOKEN)
        }
    }
    expect(document.cookie).not.toContain(RAW_TOKEN)
    for (const request of server.requests) {
        expect(request.path).not.toContain(RAW_TOKEN)
        if (request.path !== "/api/campaign-invitations/onboarding/start") {
            expect(request.body ?? "").not.toContain(RAW_TOKEN)
        }
    }
}

beforeEach(() => {
    server = new FakeServer()
    window.localStorage.clear()
    window.sessionStorage.clear()
    vi.stubGlobal(
        "fetch",
        vi.fn((input: RequestInfo | URL, init?: RequestInit) => server.handle(input, init)),
    )
})

afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, "", "/")
})

describe("invitation continuation across Login", () => {
    it("completes the existing-account flow without ever leaving the invitation page for Login", async () => {
        // Hold `start` back so any status read fired at mount (the original
        // defect) resolves first with a 404 and a stale "unavailable".
        let release!: () => void
        server.startGate = new Promise<void>((resolve) => {
            release = resolve
        })
        openInvitationLink()

        // The fragment is removed before any await.
        await waitFor(() => {
            expect(window.location.hash).toBe("")
        })
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 25))
        })
        expect(server.count("GET", "/api/campaign-invitations/onboarding/status")).toBe(0)

        await act(async () => {
            release()
        })

        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument()
        expect(screen.queryByLabelText("Email or Username")).not.toBeInTheDocument()

        await signInInline("existing", PASSWORD)

        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })).toBeInTheDocument()
        expect(screen.getAllByText("Existing User").length).toBeGreaterThan(0)
        // Signing in alone never joins.
        expect(server.completeCount).toBe(0)

        const join = screen.getByRole("button", { name: `Join ${CAMPAIGN_NAME}` })
        await waitFor(() => {
            expect(join).toBeEnabled()
        })
        const sessionReadsBefore = server.count("GET", "/auth/session")
        fireEvent.click(join)

        expect(await screen.findByRole("heading", { name: `You joined ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(screen.getByText(/GM may still need to assign a role/)).toBeInTheDocument()
        expect(server.count("POST", "/api/campaign-invitations/onboarding/complete")).toBe(1)
        expect(server.completeCount).toBe(1)
        // Bootstrap reloaded after acceptance.
        await waitFor(() => {
            expect(server.count("GET", "/auth/session")).toBeGreaterThan(sessionReadsBefore)
        })

        fireEvent.click(screen.getByRole("link", { name: "Go to campaigns" }))
        expect(await screen.findByRole("heading", { name: "Campaigns" })).toBeInTheDocument()
        expect(await screen.findByRole("heading", { name: "Mundivita" })).toBeInTheDocument()

        expectNoTokenAnywhere()
    })

    it("survives React Strict Mode with exactly one start request", async () => {
        openInvitationLink(RAW_TOKEN, true)

        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(server.count("POST", "/api/campaign-invitations/onboarding/start")).toBe(1)

        await signInInline("existing", PASSWORD)
        const join = await screen.findByRole("button", { name: `Join ${CAMPAIGN_NAME}` })
        await waitFor(() => {
            expect(join).toBeEnabled()
        })
        fireEvent.click(join)

        expect(await screen.findByRole("heading", { name: `You joined ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(server.completeCount).toBe(1)
        expectNoTokenAnywhere()
    })

    it("offers an explicit Resume choice (never auto-redirecting) after Login with a live continuation, surviving a failed attempt", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })

        // Leave for the standalone Login route while the continuation is live.
        navigateExternally("/login")
        await signInOnLoginPage("existing", "wrong password")
        expect(await screen.findByRole("alert")).toHaveTextContent("The login name or password is incorrect.")
        expect(server.sessionUser).toBeNull()

        await signInOnLoginPage("existing", PASSWORD)

        // Signing in alone neither redirects nor accepts: the user chooses.
        expect(await screen.findByRole("link", { name: "Resume invitation" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Continue" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { level: 1, name: "Home" })).not.toBeInTheDocument()
        expect(server.completeCount).toBe(0)

        fireEvent.click(screen.getByRole("link", { name: "Resume invitation" }))
        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })).toBeInTheDocument()
        expect(screen.getAllByText("Existing User").length).toBeGreaterThan(0)
        expect(server.completeCount).toBe(0)

        const join = screen.getByRole("button", { name: `Join ${CAMPAIGN_NAME}` })
        await waitFor(() => {
            expect(join).toBeEnabled()
        })
        fireEvent.click(join)
        fireEvent.click(join)

        expect(await screen.findByRole("heading", { name: `You joined ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(server.count("POST", "/api/campaign-invitations/onboarding/complete")).toBe(1)
        expectNoTokenAnywhere()
    })

    it("keeps Back/Forward from accepting or losing the continuation", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        navigateExternally("/login")
        await signInOnLoginPage("existing", PASSWORD)
        fireEvent.click(await screen.findByRole("link", { name: "Resume invitation" }))
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })

        navigateExternally(-1)
        // Resume replaced the /login entry, so Back lands on the invitation
        // entry, which resumes from the still-live continuation; nothing was
        // accepted by navigating.
        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })).toBeInTheDocument()
        expect(server.completeCount).toBe(0)
        expect(server.onboardingLive).toBe(true)
        expectNoTokenAnywhere()
    })

    it("lands through /home on the campaign list for a login with no continuation and no campaigns", async () => {
        openPlainLogin()

        await signInOnLoginPage("existing", PASSWORD)

        expect(await screen.findByRole("heading", { level: 1, name: "Campaigns" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: /^Join / })).not.toBeInTheDocument()
        expect(server.completeCount).toBe(0)
    })

    it("does not let an abandoned live continuation hijack a later ordinary login", async () => {
        // Abandoned flow: the continuation cookie is still live, but the user
        // now opens /login directly (a fresh page load, no fragment).
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        cleanup()
        expect(server.onboardingLive).toBe(true)

        openPlainLogin()
        await signInOnLoginPage("existing", PASSWORD)

        // Explicit server-confirmed choice, no automatic diversion.
        expect(await screen.findByRole("link", { name: "Resume invitation" })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: /^Join / })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "Continue" }))
        expect(await screen.findByRole("heading", { level: 1, name: "Campaigns" })).toBeInTheDocument()
        expect(server.completeCount).toBe(0)
        expect(server.members.size).toBe(0)
    })

    it("sanitizes a malformed percent-encoded fragment and fails generically without a start request", async () => {
        window.history.replaceState(null, "", "/campaign-invitations/accept#token=%E0%A4%A")
        const thrown: unknown[] = []
        const onError = (event: ErrorEvent) => {
            thrown.push(event.error)
        }
        window.addEventListener("error", onError)
        render(
            <ThemeProvider>
                <MemoryRouter initialEntries={["/campaign-invitations/accept"]}>
                    <RouteSessionProvider>
                        <App />
                    </RouteSessionProvider>
                </MemoryRouter>
            </ThemeProvider>,
        )

        expect(
            await screen.findByRole("heading", { name: "This invitation is no longer available" }),
        ).toBeInTheDocument()
        window.removeEventListener("error", onError)
        expect(thrown).toEqual([])
        expect(window.location.hash).toBe("")
        expect(window.location.href).not.toContain("%E0")
        expect(JSON.stringify(window.history.state)).not.toContain("%E0")
        expect(server.count("POST", "/api/campaign-invitations/onboarding/start")).toBe(0)
        expect(server.count("GET", "/api/campaign-invitations/onboarding/status")).toBe(0)
    })

    it("falls back to the ordinary landing when the continuation expired while on Login, and never accepts", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        navigateExternally("/login")
        await screen.findByLabelText("Email or Username")

        server.expireInvitation()
        await signInOnLoginPage("existing", PASSWORD)

        expect(await screen.findByRole("heading", { level: 1, name: "Campaigns" })).toBeInTheDocument()
        expect(server.completeCount).toBe(0)
        expect(server.members.size).toBe(0)
    })

    it("tells the user when the invitation expires between confirmation and acceptance, with no optimistic membership", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        await signInInline("existing", PASSWORD)
        const join = await screen.findByRole("button", { name: `Join ${CAMPAIGN_NAME}` })
        await waitFor(() => {
            expect(join).toBeEnabled()
        })

        server.invitationValid = false
        fireEvent.click(join)

        expect(await screen.findByRole("alert")).toHaveTextContent("This invitation is no longer available")
        expect(screen.queryByRole("heading", { name: /You joined/ })).not.toBeInTheDocument()
        expect(server.members.size).toBe(0)
    })

    it("lets a wrong account switch accounts, keeps the continuation, and never accepts for the wrong account", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        await signInInline("other", PASSWORD)
        await screen.findAllByText("Other User")

        fireEvent.click(screen.getByRole("button", { name: "Use a different account" }))

        // Signed out, back to the inline sign-in with the same continuation.
        expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument()
        expect(server.sessionUser).toBeNull()
        expect(server.onboardingLive).toBe(true)
        expect(server.completeCount).toBe(0)

        await signInInline("existing", PASSWORD)
        expect(await screen.findAllByText("Existing User")).not.toHaveLength(0)
        expect(screen.queryAllByText("Other User")).toHaveLength(0)
        expect(server.members.size).toBe(0)
    })

    it("does not accept when the user chooses Not now, and closes the continuation", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        await signInInline("existing", PASSWORD)
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })

        fireEvent.click(screen.getByRole("button", { name: "Not now" }))

        expect(await screen.findByRole("heading", { name: "Invitation not accepted" })).toBeInTheDocument()
        expect(server.completeCount).toBe(0)
        expect(server.members.size).toBe(0)
        expect(server.onboardingLive).toBe(false)
        expect(server.count("POST", "/api/campaign-invitations/onboarding/cancel")).toBe(1)
    })

    it("lets a visitor cancel from the sign-in state too", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })

        fireEvent.click(screen.getByRole("button", { name: "Not now" }))

        expect(await screen.findByRole("heading", { name: "Invitation not accepted" })).toBeInTheDocument()
        expect(server.onboardingLive).toBe(false)
        expect(server.members.size).toBe(0)
    })

    it("registers a new account through the same continuation and reloads the session", async () => {
        openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })

        const form = screen.getByRole("form", { name: "Create an account" })
        fireEvent.change(within(form).getByLabelText("Choose a login name"), { target: { value: "newcomer" } })
        fireEvent.change(within(form).getByLabelText("Display name"), { target: { value: "New Comer" } })
        fireEvent.change(within(form).getByLabelText("Choose a passphrase"), { target: { value: PASSWORD } })
        fireEvent.click(within(form).getByRole("button", { name: "Create account and join" }))

        expect(await screen.findByRole("heading", { name: `You joined ${CAMPAIGN_NAME}` })).toBeInTheDocument()
        expect(server.members.has("u-newcomer")).toBe(true)
        expect(server.count("POST", "/api/campaign-invitations/onboarding/register")).toBe(1)
        expectNoTokenAnywhere()
    })

    it("aborts an in-flight start when the page unmounts", async () => {
        let release!: () => void
        server.startGate = new Promise<void>((resolve) => {
            release = resolve
        })
        const view = openInvitationLink()
        await waitFor(() => {
            expect(server.count("POST", "/api/campaign-invitations/onboarding/start")).toBe(1)
        })

        view.unmount()
        const start = server.requests.find(
            (r) => r.path === "/api/campaign-invitations/onboarding/start",
        )
        expect(start?.signal?.aborted).toBe(true)
        release()
    })

    it("shows no stale success from a previously completed invitation on a fresh invitation open", async () => {
        const first = openInvitationLink()
        await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}` })
        await signInInline("existing", PASSWORD)
        const join = await screen.findByRole("button", { name: `Join ${CAMPAIGN_NAME}` })
        await waitFor(() => {
            expect(join).toBeEnabled()
        })
        fireEvent.click(join)
        await screen.findByRole("heading", { name: `You joined ${CAMPAIGN_NAME}` })
        first.unmount()

        // A second, fresh link open (a new page load): the old success state
        // is component-local and must not carry over.
        server.invitationValid = true
        openInvitationLink()
        expect(await screen.findByRole("heading", { name: `Join ${CAMPAIGN_NAME}?` })).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: /You joined/ })).not.toBeInTheDocument()
        expect(server.completeCount).toBe(1)
    })
})
