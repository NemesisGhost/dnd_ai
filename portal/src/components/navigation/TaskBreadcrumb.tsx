import { Link, useLocation } from "react-router"
import { breadcrumbModel } from "../../navigation/breadcrumbModel"
import { useBreadcrumbLabelReader } from "../../navigation/BreadcrumbLabelContext"
import "../authoring/authoring.css"

// The one breadcrumb for a page (docs/UI_DESIGN.md §4.8, UI_STYLE_GUIDE §8 and §10a.1).
//
// The trail follows the history entry's validated task origin: the task the person started from the
// Navbar (or an adapted legacy return key, or the route's defaults after a direct entry), never a guess
// from where the record lives. Ancestors are ordinary links, each carrying the task cut back to that
// ancestor. The current page is plain text marked `aria-current="page"`.
//
// Names: an ancestor shows a name only when a page in this tab read it under the same authority and
// registered it (navigation/BreadcrumbLabelContext). Otherwise it shows the generic noun ("Party",
// "Character"). A label never enters history, a URL or storage, and showing it grants nothing: following
// the link is authorized by the server as any navigation is.
//
// `current` is the page's own heading text when it has an authorized one (a party's name); without it
// the route's generic noun is used.
export function TaskBreadcrumb({ current }: { current?: string | null }) {
    const location = useLocation()
    const labelFor = useBreadcrumbLabelReader()
    const model = breadcrumbModel(location.pathname, location.state)
    // A page that is the top of its task (a Navbar destination) has no ancestors, and a breadcrumb of
    // only the current page says nothing the heading does not: nothing is rendered.
    if (model === null || model.ancestors.length === 0) return null
    const currentLabel = current !== undefined && current !== null && current !== "" ? current : model.current.generic
    return (
        <nav className="authoring-page__breadcrumb task-breadcrumb" aria-label="Breadcrumb">
            <ol className="task-breadcrumb__list">
                {model.ancestors.map((crumb) => (
                    <li key={`${crumb.ref.route}:${Object.values(crumb.ref.params).join("/")}`}>
                        <Link to={crumb.to} state={crumb.state}>
                            {(crumb.named ? labelFor(crumb.ref.route, crumb.ref.params) : undefined) ?? crumb.generic}
                        </Link>
                    </li>
                ))}
                <li>
                    <span aria-current="page">{currentLabel}</span>
                </li>
            </ol>
        </nav>
    )
}
