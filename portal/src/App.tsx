import { Route, Routes } from 'react-router'
import './App.css'
import { CampaignContextBar } from "./components/CampaignContextBar"
import { sessionBootstrapFixture } from './fixtures/sessionBootstrap'
import PlaceholderPage from './pages/PlaceholderPage'

function App() {
  const selectedCampaign =
    sessionBootstrapFixture.campaigns.find(
      (campaign) =>
        campaign.campaignId ===
        sessionBootstrapFixture.selectedCampaignId,
    ) ?? null

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1 className="app-header__title">D&amp;D AI Portal</h1>
      </header>

      {selectedCampaign ? (
        <CampaignContextBar campaign={selectedCampaign} />
      ) : (
        <p className="context-error" role="alert">
          No campaign is currently selected.
        </p>
      )}

      <main className="app-main">
        <Routes>
          <Route
            path="/"
            element={
              <PlaceholderPage
                title="Portal Foundation"
                description="The Phase 13 portal foundation is running."
              />
            }
          />

          <Route
            path="/login"
            element={
              <PlaceholderPage
                title="Log in"
                description="Local application authentication will be added in Phase 13B."
              />
            }
          />

          <Route
            path="/campaigns"
            element={
              <PlaceholderPage
                title="Campaigns"
                description="Select a campaign to enter the portal."
              />
            }
          />

          <Route
            path="/app/:campaignId/home"
            element={
              <PlaceholderPage
                title="Home"
                description="Campaign activity and summary information will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/world"
            element={
              <PlaceholderPage
                title="World"
                description="Authorized locations, people, factions, and lore will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/characters"
            element={
              <PlaceholderPage
                title="Characters"
                description="Authorized player and non-player character information will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/quests"
            element={
              <PlaceholderPage
                title="Quests"
                description="Known active and completed quests will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/sessions"
            element={
              <PlaceholderPage
                title="Sessions"
                description="Session history and summaries will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/knowledge"
            element={
              <PlaceholderPage
                title="Knowledge"
                description="Facts visible from the selected character perspective will appear here."
              />
            }
          />

          <Route
            path="/app/:campaignId/ask"
            element={
              <PlaceholderPage
                title="Ask"
                description="Ask campaign questions from the selected perspective."
                status="Unavailable until the Phase 12 AI features are verified."
              />
            }
          />

          <Route
            path="/app/:campaignId/access"
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
                title="Page not found"
                description="The requested portal page does not exist."
              />
            }
          />
        </Routes>
      </main>

      <footer className="app-footer">
        <p>&copy; 2026 D&amp;D AI Portal</p>
      </footer>
    </div>
  )
}

export default App