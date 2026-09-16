import { Navigate, Route, Routes } from "react-router"
import "./App.css"
import { ThemeSelector } from "./themes/ThemeSelector"
import { LogoutButton } from "./components/LogoutButton"
import { CampaignSessionBoundary } from "./layouts/CampaignSessionBoundary"
import PlaceholderPage from "./pages/PlaceholderPage"
import { LoginPage } from "./pages/LoginPage"
import { AuthenticatedSessionBoundary } from "./layouts/AuthenticatedSessionBoundary"
import { CampaignsPage } from "./pages/CampaignsPage"
import { CampaignHomePage } from "./pages/CampaignHomePage"
import { CampaignCharactersPage } from "./pages/CampaignCharactersPage"
import { CampaignQuestsPage } from "./pages/CampaignQuestsPage"
import { CampaignQuestDetailPage } from "./pages/CampaignQuestDetailPage"
import { CampaignSessionsPage } from "./pages/CampaignSessionsPage"
import { CampaignSessionDetailPage } from "./pages/CampaignSessionDetailPage"
import { CampaignWorldPage, } from "./pages/CampaignWorldPage"
import { CampaignWorldDetailPage } from "./pages/CampaignWorldDetailPage"
import { CampaignKnowledgePage } from "./pages/CampaignKnowledgePage"
import { CampaignKnowledgeDetailPage } from "./pages/CampaignKnowledgeDetailPage"

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        {/* Not an h1: each route supplies its own single page-level
            heading (docs/PLAN.md accessibility exit criterion) — this is
            persistent site-identity chrome, not a heading in the document
            outline. */}
        <p className="app-header__title">
          D&amp;D AI Portal
        </p>
        <ThemeSelector />
        <LogoutButton />
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
            <AuthenticatedSessionBoundary>
              {(bootstrap) => (
                <CampaignsPage bootstrap={bootstrap} />
              )}
            </AuthenticatedSessionBoundary>
          }
        />

        <Route
          path="/app/:campaignId"
          element={<CampaignSessionBoundary />}
        >
          <Route
            index
            element={<Navigate to="home" replace />}
          />

          <Route
            path="home"
            element={<CampaignHomePage />}
          />

          <Route
            path="world"
            element={<CampaignWorldPage />}
          />

          <Route
            path="world/:category/:entityId"
            element={<CampaignWorldDetailPage />}
          />

          <Route
            path="characters"
            element={<CampaignCharactersPage />}
          />

          <Route
            path="quests"
            element={<CampaignQuestsPage />}
          />

          <Route
            path="quests/:questId"
            element={<CampaignQuestDetailPage />}
          />

          <Route
            path="sessions"
            element={<CampaignSessionsPage />}
          />

          <Route
            path="sessions/:sessionId"
            element={<CampaignSessionDetailPage />}
          />

          <Route
            path="knowledge"
            element={<CampaignKnowledgePage />}
          />

          <Route
            path="knowledge/:knowledgeItemId"
            element={<CampaignKnowledgeDetailPage />}
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