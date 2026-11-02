import { Fragment, useLayoutEffect, useRef, useState } from "react"
import { Link, Outlet, useLocation, useNavigate, useNavigationType, useParams } from "react-router"
import { WorkspaceFrame } from "../components/WorkspaceFrame"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useSession } from "../context/SessionContext"
import { readEntryPerspective, setCommittedPerspective } from "../hooks/navigationHolds"
import { useRecordLastVisitedCampaign } from "../hooks/useRecordLastVisitedCampaign"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { SessionBootstrap } from "../types/bootstrap"

interface CampaignLayoutProps {
  bootstrap: SessionBootstrap
}

// The query parameters that carry a character perspective (and the party chosen under it). A
// perspective change must not leave the old pair in the address: pages prefer it to the selection,
// and syncCharacterFromUrl would otherwise turn the accepted change back.
const PERSPECTIVE_QUERY_KEYS = ["character_id", "party_id"] as const

function asRecord(state: unknown): Record<string, unknown> {
  return typeof state === "object" && state !== null ? (state as Record<string, unknown>) : {}
}

// The campaign workspace. A character-perspective change is a guarded context transition: it
// navigates to the same page, stamped with the requested perspective in the entry's state, and
// nothing is selected, cleared, refreshed or reloaded until the navigation is accepted (UI_DESIGN
// §4.5, §5.11). The selection is then committed from the accepted location, the page content is
// remounted under the new perspective (so every perspective-dependent read runs again), and the
// session bootstrap is revalidated in the background. Every accepted entry records the perspective it
// committed under, which is what lets Back/Forward between same-path entries be guarded.
export function CampaignLayout({ bootstrap }: CampaignLayoutProps) {
  const { campaignId } = useParams<{ campaignId: string }>()
  const { getSelectedCharacterId, selectCharacter } = usePerspective()
  const { refresh } = useSession()
  const location = useLocation()
  const navigationType = useNavigationType()
  const navigate = useNavigate()

  const campaign =
    bootstrap.campaigns.find(
      (candidate) => candidate.campaign_id === campaignId,
    ) ?? null

  // Only a campaign found in the current scope's bootstrap has passed the
  // authorization boundary; an unknown/unauthorized route is never recorded.
  useRecordLastVisitedCampaign(campaign?.campaign_id ?? null, bootstrap)

  const activeCampaignId = campaign?.campaign_id ?? null
  const selectedCharacterId =
    activeCampaignId === null ? null : getSelectedCharacterId(activeCampaignId)
  const authorized = new Set(
    campaign?.character_perspectives.map((character) => character.character_id) ?? [],
  )
  const defaultCharacterId =
    campaign !== null && authorized.has(campaign.selected_character_id ?? "")
      ? campaign.selected_character_id
      : null

  // What this location asks the workspace to run under. A stamp (or, for Back/Forward to an entry
  // with none, the default) is applied once per location; afterwards the selection may legitimately
  // move on its own (revocation, a URL-carried character) and the entry is re-stamped instead.
  const stamped = readEntryPerspective(location.state, authorized)
  const requested = stamped !== undefined ? stamped : navigationType === "POP" ? defaultCharacterId : undefined
  const [processedKey, setProcessedKey] = useState(location.key)
  const unprocessed = location.key !== processedKey
  const commitPending = unprocessed && requested !== undefined && requested !== selectedCharacterId
  const handledKey = useRef(location.key)

  useLayoutEffect(() => {
    if (activeCampaignId === null) {
      setCommittedPerspective(null)
      return
    }

    if (unprocessed && handledKey.current !== location.key) {
      handledKey.current = location.key
      setProcessedKey(location.key)
      if (requested !== undefined && requested !== selectedCharacterId) {
        // Accepted: commit before anything under the new perspective renders, and revalidate the
        // bootstrap in the background (a ticketed, coalesced read that clears a perspective it no
        // longer authorizes). The page content stays unrendered until the re-render below.
        setCommittedPerspective({ characterId: requested, defaultCharacterId, authorized })
        selectCharacter(activeCampaignId, requested)
        void Promise.resolve(refresh()).catch(() => undefined)
        return
      }
    }

    setCommittedPerspective({ characterId: selectedCharacterId, defaultCharacterId, authorized })

    // Record the committed perspective on the accepted entry. Same path and same perspective, so the
    // replacement is never guarded, adds no history entry, and does not remount anything.
    if (!commitPending && stamped !== selectedCharacterId) {
      navigate(
        { pathname: location.pathname, search: location.search, hash: location.hash },
        { replace: true, state: { ...asRecord(location.state), ctx: { v: 1, characterId: selectedCharacterId } } },
      )
    }
    // `authorized` is rebuilt every render; its content follows the bootstrap, tracked below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeCampaignId,
    bootstrap,
    commitPending,
    defaultCharacterId,
    location.key,
    requested,
    selectedCharacterId,
    stamped,
    unprocessed,
  ])

  useLayoutEffect(() => () => setCommittedPerspective(null), [])

  if (campaign === null) {
    return (
      <main className="app-main">
        <PlaceholderPage
          title="Campaign not found"
          description="The requested campaign is unavailable or you do not have access to it."
        />
        <p>
          <Link to="/campaigns">Browse campaigns</Link>
        </p>
      </main>
    )
  }

  const activeCampaign = campaign

  function requestPerspective(characterId: string | null): void {
    if (characterId === selectedCharacterId) {
      return
    }
    if (characterId !== null && !authorized.has(characterId)) {
      return
    }
    const search = new URLSearchParams(location.search)
    PERSPECTIVE_QUERY_KEYS.forEach((key) => search.delete(key))
    const query = search.toString()
    navigate(
      { pathname: location.pathname, search: query === "" ? "" : `?${query}`, hash: location.hash },
      { state: { ...asRecord(location.state), ctx: { v: 1, characterId } } },
    )
  }

  return (
    <WorkspaceFrame
      campaign={activeCampaign}
      selectedCharacterId={selectedCharacterId}
      onSelectCharacter={requestPerspective}
    >
      {/* Keyed on campaign and perspective, never the location: every perspective-dependent page
          remounts (and reads again) when the perspective changes, and nothing else does. */}
      <Fragment key={`${activeCampaign.campaign_id}:${selectedCharacterId ?? "none"}`}>
        {commitPending ? null : <Outlet />}
      </Fragment>
    </WorkspaceFrame>
  )
}
