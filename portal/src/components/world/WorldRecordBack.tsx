import { Link, useLocation } from "react-router"
import { useWorldBackPath } from "../../hooks/useWorldBackPath"
import { taskOf } from "../../navigation/breadcrumbModel"
import { TaskBreadcrumb } from "../navigation/TaskBreadcrumb"

// The way back from a read-only World page (a place, organization, religion, event or item). Opened
// inside a task (the World browser with its filters, a character's inventory, an event's explanation) the
// shared breadcrumb shows that task; opened any other way, or when the page cannot say where the person
// came from, it keeps the "Back to World" link it has always had. A place's containment is not consulted:
// where a record sits in the world is a fact about the record (its Location path), not how it was opened.
export function WorldRecordBack({ campaignId, current }: { campaignId: string; current: string }) {
    const location = useLocation()
    const worldBack = useWorldBackPath(campaignId)
    if (taskOf(location.pathname, location.state) !== null) return <TaskBreadcrumb current={current} />
    return (
        <p>
            <Link to={worldBack}>Back to World</Link>
        </p>
    )
}
