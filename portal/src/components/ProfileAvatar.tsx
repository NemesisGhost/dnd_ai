import { UserRound } from "lucide-react"
import type { ProfileAvatarModel } from "../utils/profileIdentity"

interface ProfileAvatarProps {
    model: ProfileAvatarModel
}

// Purely decorative — the profile-menu button supplies its own
// aria-label, so this never needs its own accessible name.
export function ProfileAvatar({ model }: ProfileAvatarProps) {
    switch (model.kind) {
        case "image":
            return (
                <img
                    className="profile-menu__avatar profile-menu__avatar--image"
                    src={model.url}
                    alt=""
                    aria-hidden="true"
                />
            )

        case "initials":
            return (
                <span
                    className="profile-menu__avatar profile-menu__avatar--initials"
                    aria-hidden="true"
                >
                    {model.text}
                </span>
            )

        case "icon":
            return (
                <span
                    className="profile-menu__avatar profile-menu__avatar--icon"
                    aria-hidden="true"
                >
                    <UserRound aria-hidden="true" />
                </span>
            )
    }
}
