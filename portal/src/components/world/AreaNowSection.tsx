import { Link } from "react-router"
import { LocationCurrentState } from "../../pages/WorldLocationDetailPage"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { LocationDetail } from "../../types/world"
import { playBlockedText } from "./worldStages"

interface Props {
    location: LocationDetail
    lifecycleView: EntityLifecycleView | null
    // The area's edit page, which holds the controls that record what is happening in the area.
    editHref: string
    editState?: object
}

// What is true of a dungeon area in this campaign's timeline (searched, destroyed, alarm level,
// notes). It is timeline state, recorded as events and apart from the area's definition; it can be
// recorded only for a published area. The controls live on the area's edit page; this section
// shows the current facts and leads there, so there is one implementation of the commands.
export function AreaNowSection({ location, lifecycleView, editHref, editState }: Props) {
    const blocked = playBlockedText(lifecycleView, "area")
    return (
        <>
            <LocationCurrentState location={location} embedded />
            {blocked !== null ? (
                <p className="authoring-note">{blocked}</p>
            ) : lifecycleView === null ? (
                <p className="authoring-note" role="status">
                    The area&apos;s status could not be loaded, so recording what happens here is not offered.
                </p>
            ) : (
                <>
                    <p className="authoring-note">
                        Recording what is happening here does not change the area itself.
                    </p>
                    <p className="authoring-page__actions-row">
                        <Link className="authoring-button" to={editHref} state={editState}>
                            Record what is happening here
                        </Link>
                    </p>
                </>
            )}
        </>
    )
}
