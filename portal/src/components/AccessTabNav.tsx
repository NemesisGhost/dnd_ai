import { NavLink } from "react-router"

interface AccessTabNavProps {
    campaignId: string
}

// A second-level tab strip local to the Access section (Phase 13E-B
// manual-acceptance fix, extended by the Access/Invitations navigation
// redesign): "Access management", "Invitations", and "Audit history" are
// three separate routes, not three panels of one page, so each can be
// reloaded directly and neither fetches another tab's data while it isn't
// the active one. `end` on the management link keeps it from also
// matching the longer `/access/invitations` and `/access/audit` paths --
// NavLink otherwise matches by prefix.
export function AccessTabNav({ campaignId }: AccessTabNavProps) {
    const accessPath = `/app/${campaignId}/access`

    return (
        <nav className="access-tab-nav" aria-label="Access">
            <ul className="access-tab-nav__list">
                <li>
                    <NavLink
                        end
                        to={accessPath}
                        className={({ isActive }) =>
                            isActive
                                ? "access-tab-nav__link access-tab-nav__link--active"
                                : "access-tab-nav__link"
                        }
                    >
                        Access management
                    </NavLink>
                </li>
                <li>
                    <NavLink
                        to={`${accessPath}/invitations`}
                        className={({ isActive }) =>
                            isActive
                                ? "access-tab-nav__link access-tab-nav__link--active"
                                : "access-tab-nav__link"
                        }
                    >
                        Invitations
                    </NavLink>
                </li>
                <li>
                    <NavLink
                        to={`${accessPath}/audit`}
                        className={({ isActive }) =>
                            isActive
                                ? "access-tab-nav__link access-tab-nav__link--active"
                                : "access-tab-nav__link"
                        }
                    >
                        Audit history
                    </NavLink>
                </li>
            </ul>
        </nav>
    )
}
