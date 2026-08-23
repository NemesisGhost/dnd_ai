import { CampaignContextBar } from "./components/CampaignContextBar"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import "./App.css"

function App() {
  const selectedCampaign = sessionBootstrapFixture.campaigns.find(
    (campaign) =>
      campaign.campaignId ===
      sessionBootstrapFixture.selectedCampaignId,
  )

  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="app-header__title">D&amp;D AI Portal</p>
      </header>

      {selectedCampaign === undefined ? (
        <div className="campaign-context-error" role="alert">
          The selected campaign is unavailable.
        </div>
      ) : (
        <CampaignContextBar campaign={selectedCampaign} />
      )}

      <main className="app-main">
        <h1>Portal Foundation</h1>
        <p>
          This Phase 13A interface uses fixture data while the
          application services are being completed.
        </p>
      </main>

      <footer className="app-footer">
        <small>Phase 13A — Fixture data only</small>
      </footer>
    </div>
  )
}

export default App