import { Navigate, Route, Routes } from "react-router"
import "./App.css"
import { CampaignSessionBoundary } from "./layouts/CampaignSessionBoundary"
import PlaceholderPage from "./pages/PlaceholderPage"
import { LoginPage } from "./pages/LoginPage"

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1 className="app-header__title">D&amp;D AI Portal</h1>
      </header>

      <Routes>
        <Route
          path="/"
          element={
            <main className="app-main">
              <PlaceholderPage
                title="Portal Foundation"
                description="The Phase 13 portal foundation is running."
              />
            </main>
          }
        />

        <Route
          path="/login"
          element={<LoginPage />}
        />

        <Route
          path="/campaigns"
          element={
            <main className="app-main">
              <PlaceholderPage
                title="Campaigns"
                description="Select a campaign to enter the portal."
              />
            </main>
          }
        />

        <Route
          path="/app/:campaignId"
          element={<CampaignSessionBoundary />}
        >
          <Route index element={<Navigate to="home" replace />} />

          <Route
            path="home"
            element={
              <PlaceholderPage
                title="Home"
                description="Campaign activity and summary information will appear here."
              />
            }
          />

          <Route
            path="world"
            element={
              <PlaceholderPage
                title="World"
                description="Authorized locations, people, factions, and lore will appear here."
              />
            }
          />

          <Route
            path="characters"
            element={
              <PlaceholderPage
                title="Characters"
                description="Authorized player and non-player character information will appear here."
              />
            }
          />

          <Route
            path="quests"
            element={
              <PlaceholderPage
                title="Quests"
                description="Known active and completed quests will appear here."
              />
            }
          />

          <Route
            path="sessions"
            element={
              <PlaceholderPage
                title="Sessions"
                description="Session history and summaries will appear here."
              />
            }
          />

          <Route
            path="knowledge"
            element={
              <PlaceholderPage
                title="Knowledge"
                description="Facts visible from the selected character perspective will appear here."
              />
            }
          />

          <Route
            path="ask"
            element={
              <PlaceholderPage
                title="Ask"
                description="Ask campaign questions from the selected perspective."
                status="Unavailable until the Phase 12 AI features are verified."
              />
            }
          />

          <Route
            path="access"
            element={
              <PlaceholderPage
                title="Access management"
                description="GM account, role, relationship, and grant management will appear here."
              />
            }
          />

          <Route
            path="*"
            element={
              <PlaceholderPage
                title="Campaign page not found"
                description="The requested campaign page does not exist."
              />
            }
          />
        </Route>

        <Route
          path="*"
          element={
            <main className="app-main">
              <PlaceholderPage
                title="Page not found"
                description="The requested portal page does not exist."
              />
            </main>
          }
        />
      </Routes>

      <footer className="app-footer">
        <p>&copy; 2026 D&amp;D AI Portal</p>
      </footer>
    </div>
  )
}

export default App