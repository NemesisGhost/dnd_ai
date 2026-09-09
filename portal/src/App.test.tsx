import {
  render,
  screen,
  within,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import App from "./App"
import { ThemeProvider } from "./themes/ThemeProvider"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { sessionBootstrapFixture } from "./fixtures/sessionBootstrap"
import { useCampaignSessions } from "./hooks/useCampaignSessions"
import { useCampaignSession } from "./hooks/useCampaignSession"
import { useCampaignSummary } from "./hooks/useCampaignSummary"
import { useCampaignQuests } from "./hooks/useCampaignQuests"
import { useCharacter } from "./hooks/useCharacter"
import { useQuest } from "./hooks/useQuest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import type {
  CampaignSessionDetail,
  CampaignSessionListItem,
} from "./types/campaignSession"
import type {
  CampaignSummary,
} from "./types/campaignSummary"

vi.mock("./hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))

vi.mock("./hooks/useCampaignSummary", () => ({
  useCampaignSummary: vi.fn(),
}))

vi.mock("./hooks/useCharacter", () => ({
  useCharacter: vi.fn(),
}))

vi.mock("./hooks/useCampaignSessions", () => ({
  useCampaignSessions: vi.fn(),
}))

vi.mock("./hooks/useCampaignSession", () => ({
  useCampaignSession: vi.fn(),
}))

vi.mock("./hooks/useCampaignQuests", () => ({
  useCampaignQuests: vi.fn(),
}))

vi.mock("./hooks/useQuest", () => ({
  useQuest: vi.fn(),
}))

const useSessionBootstrapMock = vi.mocked(
  useSessionBootstrap,
)

const useCampaignSummaryMock = vi.mocked(
  useCampaignSummary,
)

const useCharacterMock = vi.mocked(
  useCharacter,
)

const useCampaignSessionsMock = vi.mocked(
  useCampaignSessions,
)

const useCampaignSessionMock = vi.mocked(
  useCampaignSession,
)

const useCampaignQuestsMock = vi.mocked(
  useCampaignQuests,
)

const useQuestMock = vi.mocked(
  useQuest,
)

const emptyCampaignSummary = {
  current_session: null,
  previous_session_recap: null,
  recent_events: [],
} satisfies CampaignSummary

const campaignSessions = [
  {
    session_id: "session-2",
    session_number: 2,
    title: "Most Recent Session",
    status_code: "completed",
    started_at: "2026-02-01T18:00:00Z",
    ended_at: "2026-02-01T22:00:00Z",
  },
] satisfies CampaignSessionListItem[]

const campaignSessionDetail = {
  session_id: "session-detail",
  session_number: 12,
  title: "The Glass Ossuary",
  status_code: "ended",
  started_at: "2026-08-30T18:00:00Z",
  ended_at: "2026-08-30T22:00:00Z",
  summary: "The party entered the dormant facility.",
  start_world_time_id: "world-time-start",
  end_world_time_id: "world-time-end",
  events: [],
} satisfies CampaignSessionDetail

const campaignQuests = [
  {
    quest_id: "quest-detail",
    name: "Restore the Glass Ossuary",
    status_code: "active",
  },
]

const campaignQuestDetail = {
  quest_id: "quest-detail",
  name: "Restore the Glass Ossuary",
  status_code: "active",
  stages: [],
}

beforeEach(() => {
  localStorage.removeItem("dnd-ai-theme")

  useSessionBootstrapMock.mockReset()

  useSessionBootstrapMock.mockReturnValue({
    state: {
      status: "authenticated",
      bootstrap: sessionBootstrapFixture,
    },
    reload: vi.fn(),
  })

  useCampaignSummaryMock.mockReset()

  useCampaignSummaryMock.mockReturnValue({
    state: {
      status: "success",
      summary: emptyCampaignSummary,
    },
    retry: vi.fn(),
  })

  useCharacterMock.mockReset()

  useCharacterMock.mockReturnValue({
    state: {
      status: "unavailable",
    },
    retry: vi.fn(),
  })

  useCampaignSessionsMock.mockReset()

  useCampaignSessionsMock.mockReturnValue({
    state: {
      status: "success",
      sessions: campaignSessions,
    },
    retry: vi.fn(),
  })

  useCampaignSessionMock.mockReset()

  useCampaignSessionMock.mockReturnValue({
    state: {
      status: "success",
      session: campaignSessionDetail,
    },
    retry: vi.fn(),
  })

  useCampaignQuestsMock.mockReset()

  useCampaignQuestsMock.mockReturnValue({
    state: {
      status: "success",
      quests: campaignQuests,
    },
    retry: vi.fn(),
  })

  useQuestMock.mockReset()

  useQuestMock.mockReturnValue({
    state: {
      status: "success",
      quest: campaignQuestDetail,
    },
    retry: vi.fn(),
  })
})

function renderAppAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <RouteSessionProvider>
          <App />
        </RouteSessionProvider>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe("portal routing", () => {
  it("shows login without campaign navigation for an unauthenticated user", () => {
    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "unauthenticated",
      },
      reload: vi.fn(),
    })

    renderAppAt("/login")

    expect(
      screen.getByRole("heading", {
        name: "D&D AI World",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("button", {
        name: "Sign In",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("shows campaign navigation and disables unavailable Ask", () => {
    renderAppAt("/app/mundivita/home")

    expect(
      screen.getByRole("navigation", {
        name: "Campaign",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Home",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      screen.queryByRole("link", {
        name: "Ask",
      }),
    ).not.toBeInTheDocument()

    const disabledAsk = screen.getByTitle(
      "Unavailable until Phase 12 is verified",
    )

    expect(disabledAsk).toHaveAttribute("aria-disabled", "true")
    expect(
      screen.queryByRole("link", { name: "Ask" }),
    ).not.toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Access",
      }),
    ).toBeInTheDocument()

    expect(
      within(
        screen.getByRole("navigation", { name: "Campaign" }),
      ).queryByRole("link", {
        name: "Change campaign",
      }),
    ).not.toBeInTheDocument()

    expect(
      within(screen.getByRole("main")).getByRole("combobox", {
        name: "Campaign",
      }),
    ).toHaveValue("mundivita")

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Home",
      }),
    ).toBeInTheDocument()
  })

  it("does not disclose campaign chrome for an unknown campaign", () => {
    renderAppAt("/app/not-a-real-campaign/home")

    expect(
      screen.getByRole("heading", {
        name: "Campaign not found",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("navigation", {
        name: "Campaign",
      }),
    ).not.toBeInTheDocument()
  })

  it("routes Characters to the selected character workspace", () => {
    renderAppAt("/app/mundivita/characters")

    expect(
      screen.getByRole("link", {
        name: "Characters",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      useCharacterMock,
    ).toHaveBeenCalledWith(
      "mundivita",
      "character-ixamarra",
    )

    expect(
      screen.getByRole("heading", {
        name: "Character unavailable",
      }),
    ).toBeInTheDocument()
  })

  it("routes Quests through the selected character perspective", () => {
    renderAppAt("/app/mundivita/quests")

    expect(
      screen.getByRole("link", {
        name: "Quests",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      useCampaignQuestsMock,
    ).toHaveBeenCalledWith(
      "mundivita",
      "character-ixamarra",
    )

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Quests",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Restore the Glass Ossuary",
      }),
    ).toHaveAttribute(
      "href",
      "/app/mundivita/quests/quest-detail",
    )
  })

  it("routes a quest ID through the quest-detail boundary", () => {
    renderAppAt(
      "/app/mundivita/quests/quest-detail",
    )

    expect(
      useQuestMock,
    ).toHaveBeenCalledWith(
      "mundivita",
      "quest-detail",
      "character-ixamarra",
    )

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Restore the Glass Ossuary",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByText("Status: active"),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Back to quests",
      }),
    ).toHaveAttribute(
      "href",
      "/app/mundivita/quests",
    )

    expect(
      screen.getByRole("link", {
        name: "Quests",
      }),
    ).toHaveAttribute(
      "aria-current",
      "page",
    )
  })

  it("uses the campaign fallback for an unknown quest subroute", () => {
    renderAppAt(
      "/app/mundivita/quests/quest-detail/unknown",
    )

    expect(
      screen.getByRole("heading", {
        name: "Campaign page not found",
      }),
    ).toBeInTheDocument()

    expect(
      useCampaignQuestsMock,
    ).not.toHaveBeenCalled()

    expect(
      useQuestMock,
    ).not.toHaveBeenCalled()
  })

  it("routes Sessions through the campaign sessions boundary", () => {
    renderAppAt("/app/mundivita/sessions")

    expect(
      screen.getByRole("link", {
        name: "Sessions",
      }),
    ).toHaveAttribute("aria-current", "page")

    expect(
      useCampaignSessionsMock,
    ).toHaveBeenCalledWith("mundivita")

    expect(
      screen.getByRole("heading", {
        name: "Sessions",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("table", {
        name: "Sessions",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Most Recent Session",
      }),
    ).toHaveAttribute(
      "href",
      "/app/mundivita/sessions/session-2",
    )
  })

  it("routes a session ID through the session-detail boundary", () => {
    renderAppAt(
      "/app/mundivita/sessions/session-detail",
    )

    expect(
      useCampaignSessionMock,
    ).toHaveBeenCalledWith(
      "mundivita",
      "session-detail",
    )

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "The Glass Ossuary",
      }),
    ).toBeInTheDocument()

    expect(
      screen.getByText(
        "The party entered the dormant facility.",
      ),
    ).toBeInTheDocument()

    expect(
      screen.getByRole("link", {
        name: "Back to sessions",
      }),
    ).toHaveAttribute(
      "href",
      "/app/mundivita/sessions",
    )

    expect(
      screen.getByRole("link", {
        name: "Sessions",
      }),
    ).toHaveAttribute(
      "aria-current",
      "page",
    )
  })

  it("provides global appearance selection in the header", () => {
    renderAppAt("/")

    const header = screen.getByRole("banner")

    expect(
      within(header).getByRole("combobox", {
        name: "Appearance",
      }),
    ).toHaveValue("system")

    expect(
      within(header).getByText(
        "Active theme: Hearthstone",
      ),
    ).toBeInTheDocument()
  })
})