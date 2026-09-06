import { useId } from "react"
import { Link } from "react-router"
import type { InfoBoxProps } from "../types/infobox"

// Generic Wiki-style infobox. Presentational only: it renders whatever
// title/sections/links it is given and holds no entity-specific knowledge,
// authorization logic, or filtering. Domain wrappers (e.g. CampaignInfoBox)
// are responsible for deciding what is safe and useful to include.
export function InfoBox({
  title,
  subtitle,
  image,
  status,
  sections,
  relatedLinks,
}: InfoBoxProps) {
  const titleId = useId()

  const sectionsWithRows = sections.filter(
    (section) => section.rows.length > 0,
  )

  const relatedLinksToShow = relatedLinks ?? []

  return (
    <aside className="infobox" aria-labelledby={titleId}>
      {image && (
        <div className="infobox__image">
          <img src={image.src} alt={image.alt} />
        </div>
      )}

      <div className="infobox__header">
        <h2 id={titleId} className="infobox__title">
          {title}
        </h2>

        {subtitle && (
          <p className="infobox__subtitle">{subtitle}</p>
        )}
      </div>

      {status !== undefined && status !== null && (
        <p className="infobox__status">{status}</p>
      )}

      {sectionsWithRows.map((section, index) => (
        <div
          className="infobox__section"
          key={section.heading ?? index}
        >
          {section.heading && (
            <h3 className="infobox__section-heading">
              {section.heading}
            </h3>
          )}

          <dl className="infobox__rows">
            {section.rows.map((row) => (
              <div className="infobox__row" key={row.label}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}

      {relatedLinksToShow.length > 0 && (
        <nav
          className="infobox__related"
          aria-label={`Related to ${title}`}
        >
          <h3 className="infobox__section-heading">
            Related
          </h3>

          <ul className="infobox__related-list">
            {relatedLinksToShow.map((link) => (
              <li key={link.to}>
                <Link
                  className="infobox__related-link"
                  to={link.to}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </aside>
  )
}
