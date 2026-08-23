interface PlaceholderPageProps {
  title: string
  description: string
  status?: string
}

function PlaceholderPage({
  title,
  description,
  status,
}: PlaceholderPageProps) {
  return (
    <section className="placeholder-page">
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