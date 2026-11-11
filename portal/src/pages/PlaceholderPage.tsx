import { LOADING_ATTRIBUTE } from "../navigation/selectionArrival"

interface PlaceholderPageProps {
  title: string
  description: string
  status?: string
  // The page is still loading its content. It says so to assistive technology and tells the selection
  // arrival not to focus this heading, which a loaded page is about to replace.
  busy?: boolean
}

function PlaceholderPage({
  title,
  description,
  status,
  busy,
}: PlaceholderPageProps) {
  return (
    <section
      className="placeholder-page"
      aria-busy={busy ? true : undefined}
      {...(busy ? { [LOADING_ATTRIBUTE]: "true" } : {})}
    >
      <h1>{title}</h1>
      <p>{description}</p>

      {status && (
        <p className="placeholder-page__status" role="status">
          {status}
        </p>
      )}
    </section>
  )
}

export default PlaceholderPage
