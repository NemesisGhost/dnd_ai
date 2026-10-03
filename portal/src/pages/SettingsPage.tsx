import { CampaignStartupForm } from "../components/CampaignStartupForm"
import { ThemeSelector } from "../themes/ThemeSelector"
import type { SessionBootstrap } from "../types/bootstrap"

interface SettingsPageProps {
    bootstrap: SessionBootstrap
    reload: () => void
}

// Personal portal settings (UI_DESIGN §4.7), reached from the account menu.
//
// Appearance reuses the existing client-side ThemeSelector: the theme stays
// in browser storage so it applies before authentication, and nothing about
// it is sent to or stored by the server. Campaign startup is the durable,
// user-scoped preference the /home landing resolver reads.
export function SettingsPage({ bootstrap, reload }: SettingsPageProps) {
    return (
        <main className="app-main">
            <section className="settings-page" aria-labelledby="settings-heading">
                <h1 id="settings-heading">Settings</h1>

                <section
                    className="settings-page__section"
                    aria-labelledby="settings-appearance-heading"
                >
                    <h2 id="settings-appearance-heading">Appearance</h2>
                    <ThemeSelector />
                </section>

                <section
                    className="settings-page__section"
                    aria-labelledby="settings-startup-heading"
                >
                    <h2 id="settings-startup-heading">Campaign startup</h2>
                    <CampaignStartupForm bootstrap={bootstrap} onCheckSession={reload} />
                </section>
            </section>
        </main>
    )
}
