import { Fragment, useContext, useLayoutEffect, useRef, useState } from "react"
import type { Location } from "react-router"
import {
  Link,
  Outlet,
  UNSAFE_DataRouterContext,
  useLocation,
  useNavigate,
  useNavigationType,
  useParams,
} from "react-router"
import { WorkspaceFrame } from "../components/WorkspaceFrame"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { useSession } from "../context/SessionContext"
import { readEntryPerspective, runPermissionLossCleanup, setCommittedPerspective } from "../hooks/navigationHolds"
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

const REVOKED_NOTICE = "Your selected character is no longer available."

function asRecord(state: unknown): Record<string, unknown> {
  return typeof state === "object" && state !== null ? (state as Record<string, unknown>) : {}
}

function withoutPerspectiveQuery(search: string): string {
  const params = new URLSearchParams(search)
  PERSPECTIVE_QUERY_KEYS.forEach((key) => params.delete(key))
  const query = params.toString()
  return query === "" ? "" : `?${query}`
}

// The campaign workspace. A character-perspective change is a guarded context transition: it
// navigates to the same page, stamped with the requested perspective in the entry's state, and
// nothing is selected, cleared, refreshed or reloaded until the navigation is accepted (UI_DESIGN
// §4.5, §5.11). The selection is then committed from the accepted location, the page content is
// remounted under the new perspective (so every perspective-dependent read runs again), and the
// session bootstrap is revalidated in the background. Every accepted entry records the perspective it
// committed under, which is what lets Back/Forward between same-path entries be guarded.
//
// A selected perspective the bootstrap stops authorizing is cleared at once, as an explicit choice of
// no perspective (never the server default, and never restored by re-authorization), without a
// question: the content remounts, an address that still names it is cleaned, and a polite notice says so.
export function CampaignLayout({ bootstrap }: CampaignLayoutProps) {
  const { campaignId } = useParams<{ campaignId: string }>()
  const { getSelectedCharacterId, selectCharacter } = usePerspective()
  const { refresh } = useSession()
  const location = useLocation()
  const navigationType = useNavigationType()
  const navigate = useNavigate()
  const dataRouter = useContext(UNSAFE_DataRouterContext)?.router ?? null

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
  // with none, the default) is applied once per location, including the first one: an entry that
  // records an authorized perspective is honored before any page reads under the default. Afterwards
  // the selection may legitimately move on its own (a URL-carried character) and the entry is
  // re-stamped instead.
  const stamped = readEntryPerspective(location.state, authorized)
  const [processedKey, setProcessedKey] = useState<string | null>(null)
  // The first location is "POP" to the router but is not a return to an older entry: with no valid
  // stamp it keeps whatever the session already shows rather than resolving to the default.
  // A REPLACE never asks for a change: stamps, cleanups and a page rewriting its own query carry the
  // state they were made under, which may be older than a selection the layout has since committed.
  const requested =
    navigationType === "REPLACE"
      ? undefined
      : stamped !== undefined
        ? stamped
        : navigationType === "POP" && processedKey !== null
          ? defaultCharacterId
          : undefined
  const unprocessed = location.key !== processedKey
  const commitPending = unprocessed && requested !== undefined && requested !== selectedCharacterId
  const handledKey = useRef<string | null>(null)
  // What is committed right now, for a replacement that applies later than the render that asked for it.
  const committedNow = useRef(selectedCharacterId)
  useLayoutEffect(() => {
    committedNow.current = selectedCharacterId
  })

  // The last perspective this layout rendered while it was authorized. When the bootstrap stops
  // listing it, the selection reads as none at once and this is what remembers that a clear is due.
  const [committedId, setCommittedId] = useState<string | null>(selectedCharacterId)
  const revokedId = committedId !== null && !authorized.has(committedId) ? committedId : null
  const staleQuery = revokedId !== null && new URLSearchParams(location.search).get("character_id") === revokedId
  const [noticePath, setNoticePath] = useState<string | null>(null)

  useLayoutEffect(() => {
    if (activeCampaignId === null) {
      setCommittedPerspective(null)
      return
    }

    // A replacement that belongs to one entry. It runs only while that entry is still the router's
    // current location and nothing is pending or waiting on a decision, and is dropped the moment a
    // newer location exists (which stamps itself), so it can never overwrite a newer PUSH, REPLACE
    // or POP, or cut across a blocked one. State and the rest of the query are carried over from the
    // router's own copy of the entry.
    //
    // Permission loss is the one case that does not wait for a blocked transition: the page whose
    // question that is has just been removed, nothing will say so, and the loss may not wait for an
    // answer. Its replacement runs under the narrow exemption in `runPermissionLossCleanup`, which
    // covers exactly this entry and this call; the held navigation is cancelled by its owner as it
    // goes away, never approved.
    function replaceOwnEntry(
      entryKey: string,
      next: (current: Location) => { search: string; state: unknown },
      permissionLoss = false,
    ) {
      if (dataRouter === null) {
        const { search, state } = next(location)
        navigate({ pathname: location.pathname, search, hash: location.hash }, { replace: true, state })
        return undefined
      }
      const router = dataRouter
      let finished = false
      const finish = () => {
        finished = true
        unsubscribe()
      }
      const attempt = () => {
        if (finished) return
        const current = router.state
        if (current.location.key !== entryKey) {
          finish()
          return
        }
        const waiting =
          current.navigation.state !== "idle" ||
          (!permissionLoss && [...current.blockers.values()].some((blocker) => blocker.state === "blocked"))
        if (waiting) return
        finish()
        const { search, state } = next(current.location)
        const apply = () =>
          void router.navigate(
            { pathname: current.location.pathname, search, hash: current.location.hash },
            { replace: true, state, preventScrollReset: true },
          )
        if (permissionLoss) runPermissionLossCleanup(entryKey, apply)
        else apply()
      }
      const unsubscribe = router.subscribe(attempt)
      attempt()
      return finish
    }

    if (unprocessed) {
      // StrictMode runs this effect twice before the state below renders.
      if (handledKey.current === location.key) return
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

    // The bootstrap default only initializes the selection. Once a perspective is in use, however it
    // was reached, it is stored as the selection (idempotently), so a later bootstrap that names a
    // different default can never replace it: losing it leaves no perspective, not the new default.
    if (revokedId === null && selectedCharacterId !== null) selectCharacter(activeCampaignId, selectedCharacterId)

    if (revokedId !== null) {
      // First the address: the page must not read as the perspective that was just lost.
      if (staleQuery) {
        return replaceOwnEntry(
          location.key,
          (current) => ({
            search: withoutPerspectiveQuery(current.search),
            state: { ...asRecord(current.state), ctx: { v: 1, characterId: null } },
          }),
          true,
        )
      }
      // Then the explicit clear: stored as a choice of no perspective, so neither the server default
      // nor a later re-authorization brings the lost one (or any other) back.
      selectCharacter(activeCampaignId, null)
      // These record that the clear has been made; they follow the selection commit just above and
      // cannot be derived during render, where the loss would no longer be visible.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCommittedId(null)
      setNoticePath(location.pathname)
      return
    }
    if (committedId !== selectedCharacterId) setCommittedId(selectedCharacterId)

    // Record the committed perspective on the accepted entry. Same path and same perspective, so the
    // replacement is never guarded, adds no history entry, and does not remount anything.
    if (!commitPending && stamped !== selectedCharacterId) {
      return replaceOwnEntry(location.key, (current) => ({
        search: current.search,
        state: { ...asRecord(current.state), ctx: { v: 1, characterId: committedNow.current } },
      }))
    }
    // `authorized` is rebuilt every render; its content follows the bootstrap, tracked below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeCampaignId,
    bootstrap,
    commitPending,
    committedId,
    dataRouter,
    defaultCharacterId,
    location.key,
    requested,
    revokedId,
    selectedCharacterId,
    stamped,
    staleQuery,
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
    navigate(
      { pathname: location.pathname, search: withoutPerspectiveQuery(location.search), hash: location.hash },
      { state: { ...asRecord(location.state), ctx: { v: 1, characterId } } },
    )
  }

  const showNotice = noticePath === location.pathname && selectedCharacterId === null

  return (
    <WorkspaceFrame
      campaign={activeCampaign}
      selectedCharacterId={selectedCharacterId}
      onSelectCharacter={requestPerspective}
    >
      {showNotice ? (
        <p className="authoring-message authoring-message--warning" role="status">
          {REVOKED_NOTICE}
        </p>
      ) : null}
      {/* Keyed on campaign and perspective, never the location: every perspective-dependent page
          remounts (and reads again) when the perspective changes, and nothing else does. Nothing
          renders while a commit is pending or the address still names a perspective just lost. */}
      <Fragment key={`${activeCampaign.campaign_id}:${selectedCharacterId ?? "none"}`}>
        {commitPending || staleQuery ? null : <Outlet />}
      </Fragment>
    </WorkspaceFrame>
  )
}
