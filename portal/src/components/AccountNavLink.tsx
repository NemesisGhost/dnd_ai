import { Link } from "react-router"
import { useSession } from "../context/SessionContext"

// Self-gating, mirroring LogoutButton/AdminAccountsNavLink's identical
// pattern — visible to any authenticated user (unlike AdminAccountsNavLink,
// which additionally requires is_platform_administrator).
export function AccountNavLink() {
    const { state } = useSession()

    if (state.status !== "authenticated") {
        return null
    }

    return <Link to="/account">Your account</Link>
}
