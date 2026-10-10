import PlaceholderPage from "./PlaceholderPage"

// The not-found content itself, for a route already inside a workspace frame
// that owns the page's <main> (an unauthorized world creation or edit route).
export function NotFoundContent() {
  return (
    <PlaceholderPage
      title="Page not found"
      description="The requested portal page does not exist."
    />
  )
}

// One shared, non-disclosing presentation for unknown routes and for the
// unauthorized /platform/accounts, /worlds/new, and /worlds/:worldId/edit
// routes, so none can be told apart (navigation plan §3.1, §6 non-disclosure).
export function NotFoundPage() {
  return (
    <main className="app-main">
      <NotFoundContent />
    </main>
  )
}
