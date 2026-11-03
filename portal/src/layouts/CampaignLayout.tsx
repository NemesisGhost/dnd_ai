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
import { setCommittedPerspective } from "../hooks/navigationHolds"
import { asRecord, replaceOwnEntry } from "../navigation/replaceOwnEntry"
import {
  entryContextStamp,
  entryContextWithinScope,
  perspectiveOfRead,
  readEntryContext,
  stampEquals,
} from "../navigation/contexts"
// A perspective change must not leave the old character/party query pair in the address: pages prefer
// it to the selection, and syncCharacterFromUrl would otherwise turn the accepted change back.
import { PERSPECTIVE_QUERY_KEYS } from "../navigation/queryKeys"
import { BreadcrumbLabelProvider } from "../navigation/BreadcrumbLabelProvider"
import { useRecordLastVisitedCampaign } from "../hooks/useRecordLastVisitedCampaign"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { SessionBootstrap } from "../types/bootstrap"

interface CampaignLayoutProps {
  bootstrap: SessionBootstrap
}

const REVOKED_NOTICE = "Your selected character is no longer available."

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
  const { getSelectedCharacterId, selectCharacter, adoptRouteCampaign } = usePerspective()
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
  // The levels the route campaign fixes. They are what an entry stamp must agree with to be honored.
  const worldId = campaign?.world_id ?? null
  const timelineId = campaign?.timeline_id ?? null
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
  // A stamp that names another campaign, world or timeline than this route's was not made under this
  // scope (foreign, tampered or stale) and is no stamp: the route scope governs.
  const stampRead = entryContextWithinScope(readEntryContext(location.state, authorized), {
    campaignId: activeCampaignId,
    worldId,
    timelineId,
  })
  const stamped = perspectiveOfRead(stampRead)
  const stampCurrent = stampEquals(stampRead, {
    campaignId: activeCampaignId,
    worldId,
    timelineId,
    characterId: selectedCharacterId,
  })
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
  // Ownership rule: a revocation owns the selection only while that selection still reads none
  // because of it. Any selection that is in place (an accepted choice, an adopted URL character)
  // has superseded the lost one, and the bookkeeping below is brought up to date instead of clearing.
  const revokedId =
    committedId !== null && !authorized.has(committedId) && selectedCharacterId === null ? committedId : null
  const staleQuery = revokedId !== null && new URLSearchParams(location.search).get("character_id") === revokedId
  const [noticePath, setNoticePath] = useState<string | null>(null)

  useLayoutEffect(() => {
    if (activeCampaignId === null) {
      setCommittedPerspective(null)
      return
    }

    // The route campaign is the selected campaign. A retained selection of another campaign is
    // replaced before anything reads under it (I-1); this campaign's own choice is kept.
    adoptRouteCampaign?.(activeCampaignId)

    // Entry-bound replacements are written by navigation/replaceOwnEntry (one implementation for the
    // stamps of every authenticated route).
    const replaceOwn = (
      entryKey: string,
      next: (current: Location) => { search: string; state: unknown },
      permissionLoss = false,
    ) => replaceOwnEntry({ router: dataRouter, navigate, location, entryKey, next, permissionLoss })

    if (unprocessed) {
      // StrictMode runs this effect twice before the state below renders.
      if (handledKey.current === location.key) return
      handledKey.current = location.key
      setProcessedKey(location.key)
      if (requested !== undefined && (requested !== selectedCharacterId || revokedId !== null)) {
        // Accepted: commit before anything under the new perspective renders, and revalidate the
        // bootstrap in the background (a ticketed, coalesced read that clears a perspective it no
        // longer authorizes). The page content stays unrendered until the re-render below. An
        // accepted location takes ownership of the selection in one step: the selection, the
        // bookkeeping that remembers the committed one, and (next) the entry's stamp all name the
        // same perspective, so a revocation of the previous selection that is still outstanding has
        // nothing left to clear, including when this location and that revocation arrive together.
        setCommittedPerspective({
          characterId: requested,
          defaultCharacterId,
          authorized,
          campaignId: activeCampaignId,
          worldId,
          timelineId,
          routeScoped: true,
        })
        selectCharacter(activeCampaignId, requested)
        // These record the commit just made (see the ownership note above).
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCommittedId(requested)
        void Promise.resolve(refresh()).catch(() => undefined)
        return
      }
    }

    setCommittedPerspective({
      characterId: selectedCharacterId,
      defaultCharacterId,
      authorized,
      campaignId: activeCampaignId,
      worldId,
      timelineId,
      routeScoped: true,
    })

    // The bootstrap default only initializes the selection. Once a perspective is in use, however it
    // was reached, it is stored as the selection (idempotently), so a later bootstrap that names a
    // different default can never replace it: losing it leaves no perspective, not the new default.
    if (revokedId === null && selectedCharacterId !== null) selectCharacter(activeCampaignId, selectedCharacterId)

    if (revokedId !== null) {
      // First the address: the page must not read as the perspective that was just lost.
      if (staleQuery) {
        return replaceOwn(
          location.key,
          (current) => ({
            search: withoutPerspectiveQuery(current.search),
            state: {
              ...asRecord(current.state),
              ctx: entryContextStamp({ campaignId: activeCampaignId, worldId, timelineId, characterId: null }),
            },
          }),
          true,
        )
      }
      // Then the explicit clear: stored as a choice of no perspective, so neither the server default
      // nor a later re-authorization brings the lost one (or any other) back.
      selectCharacter(activeCampaignId, null)
      // These record that the clear has been made; they follow the selection commit just above and
      // cannot be derived during render, where the loss would no longer be visible.
      setCommittedId(null)
      setNoticePath(location.pathname)
      return
    }
    if (committedId !== selectedCharacterId) setCommittedId(selectedCharacterId)

    // Record the committed context on the accepted entry (this also upgrades a perspective-only stamp
    // and replaces a foreign one). Same path and same context, so the replacement is never guarded,
    // adds no history entry, and does not remount anything. Unrelated router state is carried over.
    if (!commitPending && !stampCurrent) {
      return replaceOwn(location.key, (current) => ({
        search: current.search,
        state: {
          ...asRecord(current.state),
          ctx: entryContextStamp({
            campaignId: activeCampaignId,
            worldId,
            timelineId,
            characterId: committedNow.current,
          }),
        },
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
    stampCurrent,
    stamped,
    staleQuery,
    timelineId,
    unprocessed,
    worldId,
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
      {
        state: {
          ...asRecord(location.state),
          ctx: entryContextStamp({ campaignId: activeCampaign.campaign_id, worldId, timelineId, characterId }),
        },
      },
    )
  }

  const showNotice = noticePath === location.pathname && selectedCharacterId === null

  return (
    <BreadcrumbLabelProvider campaignId={activeCampaign.campaign_id} characterId={selectedCharacterId}>
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
    </BreadcrumbLabelProvider>
  )
}
