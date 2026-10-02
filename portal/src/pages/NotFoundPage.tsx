import PlaceholderPage from "./PlaceholderPage"

// One shared, non-disclosing presentation for unknown routes and for the
// unauthorized /platform/accounts route, so the two cannot be told apart
// (navigation plan §3.1, §6 non-disclosure).
export function NotFoundPage() {
  return (
    <main className="app-main">
      <PlaceholderPage
        title="Page not found"
        description="The requested portal page does not exist."
      />
    </main>
  )
}
