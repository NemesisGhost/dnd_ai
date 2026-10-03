import { Link } from "react-router"
import { useSession } from "../context/SessionContext"

// Self-gating, mirroring LogoutButton's identical pattern — renders
// nothing unless the current session is authenticated and reports
// is_platform_administrator. Presentation only: /admin/accounts and
// every mutation it drives remain the real, server-authoritative gate.
export function AdminAccountsNavLink() {
    const { state } = useSession()

    if (state.status !== "authenticated" || !state.bootstrap.is_platform_administrator) {
        return null
    }

    return <Link to="/admin/accounts">Platform accounts</Link>
}
