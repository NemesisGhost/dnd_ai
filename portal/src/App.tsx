import { Navigate, Route, Routes } from "react-router"
import "./App.css"
import { PublicLayout } from "./layouts/PublicLayout"
import { AuthenticatedAppLayout } from "./layouts/AuthenticatedAppLayout"
import { useAuthenticatedSession } from "./layouts/useAuthenticatedSession"
import { CampaignSessionBoundary } from "./layouts/CampaignSessionBoundary"
import PlaceholderPage from "./pages/PlaceholderPage"
import { NotFoundPage } from "./pages/NotFoundPage"
import { LoginPage } from "./pages/LoginPage"
import { LandingRedirect } from "./pages/LandingRedirect"
import { CampaignsPage } from "./pages/CampaignsPage"
import { CampaignHomePage } from "./pages/CampaignHomePage"
import { CampaignCharactersPage } from "./pages/CampaignCharactersPage"
import { CampaignQuestsPage } from "./pages/CampaignQuestsPage"
import { CampaignQuestDetailPage } from "./pages/CampaignQuestDetailPage"
import { CampaignSessionsPage } from "./pages/CampaignSessionsPage"
import { CampaignSessionDetailPage } from "./pages/CampaignSessionDetailPage"
import { CreateSessionPage, EditSessionPage } from "./pages/SessionFormPages"
import { SessionRunPage } from "./pages/SessionRunPage"
import { CampaignWorldPage, } from "./pages/CampaignWorldPage"
import { CampaignWorldDetailPage } from "./pages/CampaignWorldDetailPage"
import { CreateLocationPage } from "./pages/CreateLocationPage"
import { EditLocationPage } from "./pages/EditLocationPage"
import {
  CreateOrganizationPage,
  EditOrganizationPage,
} from "./pages/OrganizationAuthoringPages"
import { CreateKnowledgePage, EditKnowledgePage } from "./pages/KnowledgeAuthoringPages"
import { CharacterBuildsPage, CreateCharacterBuildPage } from "./pages/CharacterBuildPages"
import { PartyMembersPage } from "./pages/PartyMembersPage"
import { EventDetailPage, RecordEventPage } from "./pages/EventPages"
import { QuestProgressPage } from "./pages/QuestProgressPage"
import { CreatePartyPage, EditPartyPage, PartiesPage } from "./pages/PartyPages"
import {
  ChooseCharacterTypePage,
  CreateNpcPage,
  CreatePlayerCharacterPage,
  EditCharacterPage,
} from "./pages/NpcAuthoringPages"
import { CreateQuestPage, EditQuestPage } from "./pages/QuestAuthoringPages"
import { CreateReligionPage, EditReligionPage } from "./pages/ReligionAuthoringPages"
import { CampaignKnowledgePage } from "./pages/CampaignKnowledgePage"
import { CampaignKnowledgeDetailPage } from "./pages/CampaignKnowledgeDetailPage"
import { CampaignAccessPage } from "./pages/CampaignAccessPage"
import { CampaignInvitationsPage } from "./pages/CampaignInvitationsPage"
import { CampaignAccessAuditPage } from "./pages/CampaignAccessAuditPage"
import { AcceptCampaignInvitationPage } from "./pages/AcceptCampaignInvitationPage"
import { AdminAccountsPage } from "./pages/AdminAccountsPage"
import { ActivateAccountPage } from "./pages/ActivateAccountPage"
import { ResetPasswordPage } from "./pages/ResetPasswordPage"
import { AccountPage } from "./pages/AccountPage"
import { SettingsPage } from "./pages/SettingsPage"
import { WorldsPage } from "./pages/WorldsPage"
import { CreateWorldPage } from "./pages/CreateWorldPage"
import { WorldOverviewPage } from "./pages/WorldOverviewPage"
import { EditWorldPage } from "./pages/EditWorldPage"
import { CampaignSetupPage } from "./pages/CampaignSetupPage"
import { CampaignSettingsPage } from "./pages/CampaignSettingsPage"
import { CreateTimelinePage } from "./pages/CreateTimelinePage"
import { TimelinePage } from "./pages/TimelinePage"
import { TimelinesPage } from "./pages/TimelinesPage"
import { WorldWorkspaceLayout } from "./layouts/WorldWorkspaceLayout"
import { CreateCalendarPage } from "./pages/CreateCalendarPage"
import { WorldTimesPage } from "./pages/WorldTimesPage"
import { EditTimelinePage } from "./pages/EditTimelinePage"
import { CreateTimelineBranchPage } from "./pages/CreateTimelineBranchPage"

function CampaignsRoute() {
  const { bootstrap } = useAuthenticatedSession()
  return <CampaignsPage bootstrap={bootstrap} />
}

function SettingsRoute() {
  const { bootstrap, reload } = useAuthenticatedSession()
  return <SettingsPage bootstrap={bootstrap} reload={reload} />
}

function PlatformAccountsRoute() {
  const { bootstrap } = useAuthenticatedSession()

  // The route adapter itself is the gate: a non-administrator never
  // mounts AdminAccountsPage, so usePlatformAccounts never mounts either
  // and no GET /api/admin/accounts request is sent (navigation plan
  // §3.1). AdminAccountsPage keeps its own internal check as defense in
  // depth.
  if (!bootstrap.is_platform_administrator) {
    return <NotFoundPage />
  }

  return <AdminAccountsPage bootstrap={bootstrap} />
}

function App() {
  return (
    <div className="app-shell">
      <Routes>
        {/* Public / self-managed routes: no authenticated navigation; only
            the profile menu appears for an authenticated visitor. */}
        <Route element={<PublicLayout />}>
          <Route
            index
            element={<Navigate to="/login" replace />}
          />

          <Route
            path="/login"
            element={<LoginPage />}
          />

          <Route
            path="/campaign-invitations/accept"
            element={<AcceptCampaignInvitationPage />}
          />

          <Route
            path="/activate"
            element={<ActivateAccountPage />}
          />

          <Route
            path="/reset-password"
            element={<ResetPasswordPage />}
          />

          <Route
            path="*"
            element={<NotFoundPage />}
          />
        </Route>

        {/* Authenticated global shell — the single session gate. */}
        <Route element={<AuthenticatedAppLayout />}>
          {/* Landing resolver: no content, replaces itself with the
              server-resolved startup campaign or /campaigns. */}
          <Route
            path="/home"
            element={<LandingRedirect />}
          />

          <Route
            path="/settings"
            element={<SettingsRoute />}
          />

          <Route
            path="/campaigns"
            element={<CampaignsRoute />}
          />

          <Route
            path="/campaigns/new"
            element={<CampaignSetupPage />}
          />

          <Route element={<WorldWorkspaceLayout />}>
            <Route
              path="/worlds"
              element={<WorldsPage />}
            />

            <Route
              path="/worlds/new"
              element={<CreateWorldPage />}
            />

            <Route
              path="/worlds/:worldId"
              element={<WorldOverviewPage />}
            />

            <Route
              path="/worlds/:worldId/edit"
              element={<EditWorldPage />}
            />

            <Route
              path="/worlds/:worldId/calendars/new"
              element={<CreateCalendarPage />}
            />

            <Route
              path="/worlds/:worldId/timelines"
              element={<TimelinesPage />}
            />

            <Route
              path="/worlds/:worldId/timelines/new"
              element={<CreateTimelinePage />}
            />

            <Route
              path="/worlds/:worldId/timelines/:timelineId"
              element={<TimelinePage />}
            />

            <Route
              path="/worlds/:worldId/timelines/:timelineId/edit"
              element={<EditTimelinePage />}
            />

            <Route
              path="/worlds/:worldId/timelines/:timelineId/branch"
              element={<CreateTimelineBranchPage />}
            />
          </Route>

          <Route
            path="/platform/accounts"
            element={<PlatformAccountsRoute />}
          />

          <Route
            path="/account"
            element={<AccountPage />}
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
              path="world/location/new"
              element={<CreateLocationPage />}
            />

            <Route
              path="world/location/:entityId/edit"
              element={<EditLocationPage />}
            />

            <Route
              path="world/organization/new"
              element={<CreateOrganizationPage />}
            />

            <Route
              path="world/organization/:entityId/edit"
              element={<EditOrganizationPage />}
            />

            <Route
              path="world/religion/new"
              element={<CreateReligionPage />}
            />

            <Route
              path="world/religion/:entityId/edit"
              element={<EditReligionPage />}
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
              path="characters/new"
              element={<ChooseCharacterTypePage />}
            />

            <Route
              path="characters/npc/new"
              element={<CreateNpcPage />}
            />

            <Route
              path="characters/pc/new"
              element={<CreatePlayerCharacterPage />}
            />

            <Route
              path="characters/:characterId/builds"
              element={<CharacterBuildsPage />}
            />

            <Route
              path="characters/:characterId/builds/new"
              element={<CreateCharacterBuildPage />}
            />

            <Route
              path="characters/:characterId/edit"
              element={<EditCharacterPage />}
            />

            <Route
              path="quests/:questId/progress"
              element={<QuestProgressPage />}
            />

            <Route
              path="events/new"
              element={<RecordEventPage />}
            />

            <Route
              path="events/:eventId"
              element={<EventDetailPage />}
            />

            <Route
              path="parties"
              element={<PartiesPage />}
            />

            <Route
              path="parties/new"
              element={<CreatePartyPage />}
            />

            <Route
              path="parties/:partyId"
              element={<PartyMembersPage />}
            />

            <Route
              path="parties/:partyId/edit"
              element={<EditPartyPage />}
            />

            <Route
              path="world-times"
              element={<WorldTimesPage />}
            />

            <Route
              path="quests"
              element={<CampaignQuestsPage />}
            />

            <Route
              path="quests/new"
              element={<CreateQuestPage />}
            />

            <Route
              path="quests/:questId/edit"
              element={<EditQuestPage />}
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
              path="sessions/new"
              element={<CreateSessionPage />}
            />

            <Route
              path="sessions/:sessionId/run"
              element={<SessionRunPage />}
            />

            <Route
              path="sessions/:sessionId/edit"
              element={<EditSessionPage />}
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
              path="knowledge/new"
              element={<CreateKnowledgePage />}
            />

            <Route
              path="knowledge/:knowledgeItemId"
              element={<CampaignKnowledgeDetailPage />}
            />

            <Route
              path="knowledge/:knowledgeItemId/edit"
              element={<EditKnowledgePage />}
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
              path="settings"
              element={<CampaignSettingsPage />}
            />

            <Route
              path="access"
              element={<CampaignAccessPage />}
            />

            <Route
              path="access/invitations"
              element={<CampaignInvitationsPage />}
            />

            <Route
              path="access/audit"
              element={<CampaignAccessAuditPage />}
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
        </Route>

        {/* Decision D-2: keep bookmarks and prior manual-validation steps
            working under the backend's still-current /admin/accounts
            path. */}
        <Route
          path="/admin/accounts"
          element={<Navigate to="/platform/accounts" replace />}
        />
      </Routes>
    </div>
  )
}

export default App
