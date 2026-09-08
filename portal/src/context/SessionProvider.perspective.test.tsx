import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"
import { CampaignContextPanel } from "../components/CampaignContextPanel"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useSessionBootstrap } from "../hooks/useSessionBootstrap"
import { AuthenticatedSessionBoundary } from "../layouts/AuthenticatedSessionBoundary"
import type { CampaignContext, SessionBootstrap } from "../types/bootstrap"
import { usePerspective } from "./CharacterPerspectiveContext"
import { SessionProvider } from "./SessionProvider"

vi.mock("../hooks/useSessionBootstrap", () => ({
  useSessionBootstrap: vi.fn(),
}))
vi.mock("../hooks/useCharacter", () => ({
  useCharacter: () => ({
    state: { status: "unavailable" },
    retry: vi.fn(),
  }),
}))

// Connects the presentational panel to the real perspective context supplied
// by SessionProvider, the way CampaignLayout does in the app.
function ConnectedPanel({
  campaign,
}: {
  campaign: CampaignContext
}) {
  const { getSelectedCharacterId, selectCharacter } = usePerspective()

  return (
    <CampaignContextPanel
      campaign={campaign}
      campaigns={[campaign]}
      selectedCharacterId={getSelectedCharacterId(campaign.campaign_id)}
      onSelectCampaign={() => {}}
      onSelectCharacter={(characterId) =>
        selectCharacter(campaign.campaign_id, characterId)
      }
    />
  )
}

const useSessionBootstrapMock =
  vi.mocked(useSessionBootstrap)

const reload = vi.fn()

const fixtureCampaign =
  sessionBootstrapFixture.campaigns[0]

if (fixtureCampaign === undefined) {
  throw new Error(
    "The session bootstrap fixture must contain a campaign",
  )
}

const campaign = {
  ...fixtureCampaign,
  campaign_id: "campaign-a",
  selected_character_id: null,
  character_perspectives: [
    {
      character_id: "character-a",
      character_name: "Character A",
    },
    {
      character_id: "character-b",
      character_name: "Character B",
    },
  ],
}

const bootstrap: SessionBootstrap = {
  ...sessionBootstrapFixture,
  browser_session_id: "session-a",
  selected_campaign_id: "campaign-a",
  campaigns: [campaign],
}

function TestPortal() {
  return (
    <MemoryRouter>
      <SessionProvider>
        <AuthenticatedSessionBoundary>
          {(sessionBootstrap) => {
            const currentCampaign =
              sessionBootstrap.campaigns[0]

            return currentCampaign === undefined
              ? null
              : (
                <ConnectedPanel campaign={currentCampaign} />
              )
          }}
        </AuthenticatedSessionBoundary>
      </SessionProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useSessionBootstrapMock.mockReset()
  reload.mockReset()

  useSessionBootstrapMock.mockReturnValue({
    state: {
      status: "authenticated",
      bootstrap,
    },
    reload,
  })
})

describe("SessionProvider perspective integration", () => {
  it("keeps the dropdown and summary synchronized after refresh", () => {
    const { rerender } = render(<TestPortal />)

    expect(
      screen.getByText(
        "Campaign context: Mundivita — Viewing as No character selected",
        { selector: "summary" },
      ),
    ).toBeInTheDocument()

    fireEvent.change(
      screen.getByRole("combobox", {
        name: "Character perspective",
      }),
      {
        target: {
          value: "character-b",
        },
      },
    )

    expect(reload).toHaveBeenCalledTimes(1)

    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "loading",
      },
      reload,
    })

    rerender(<TestPortal />)

    expect(
      screen.getByRole("heading", {
        name: "Loading portal",
      }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("combobox", {
        name: "Character perspective",
      }),
    ).not.toBeInTheDocument()

    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "authenticated",
        bootstrap,
      },
      reload,
    })

    rerender(<TestPortal />)

    expect(
      screen.getByRole("combobox", {
        name: "Character perspective",
      }),
    ).toHaveValue("character-b")

    expect(
      screen.getByText(
        "Campaign context: Mundivita — Viewing as Character B",
        { selector: "summary" },
      ),
    ).toBeInTheDocument()
  })

  it("removes a revoked perspective and displays the authorized server default", () => {
    const { rerender } = render(<TestPortal />)

    fireEvent.change(
      screen.getByRole("combobox", {
        name: "Character perspective",
      }),
      {
        target: {
          value: "character-b",
        },
      },
    )

    expect(reload).toHaveBeenCalledTimes(1)

    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "loading",
      },
      reload,
    })

    rerender(<TestPortal />)

    useSessionBootstrapMock.mockReturnValue({
      state: {
        status: "authenticated",
        bootstrap: {
          ...bootstrap,
          campaigns: [
            {
              ...campaign,
              selected_character_id: "character-a",
              character_perspectives:
                campaign.character_perspectives.filter(
                  (character) =>
                    character.character_id ===
                    "character-a",
                ),
            },
          ],
        },
      },
      reload,
    })

    rerender(<TestPortal />)

    expect(
      screen.getByRole("combobox", {
        name: "Character perspective",
      }),
    ).toHaveValue("character-a")

    expect(
      screen.getByText(
        "Campaign context: Mundivita — Viewing as Character A",
        { selector: "summary" },
      ),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole("option", {
        name: "Character B",
      }),
    ).not.toBeInTheDocument()

    expect(
      screen.queryByText(
        "Campaign context: Mundivita — Viewing as Character B",
        { selector: "summary" },
      ),
    ).not.toBeInTheDocument()
  })
})