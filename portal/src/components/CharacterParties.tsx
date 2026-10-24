import { Link } from "react-router"
import { characterPartiesPath } from "../api/parties"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { CharacterParties as CharacterPartiesData } from "../types/parties"

interface CharacterPartiesProps {
  campaignId: string
  characterId: string
}

// The selected character's party memberships, as a collapsed "Parties (N)" disclosure under the
// character selector. It is an affiliation list only: expanding it or opening a party never
// changes the Knowledge filters, the selected party or what any character knows.
//
// The list is the server's complete current membership for this campaign and timeline, so the
// count is exactly what may be shown. It is requested per (campaign, character) and the resource
// state is keyed by that request, so one character's parties are never shown under another's
// while the next load is in flight, and the Info Box remounts this per (campaign, character), so
// the disclosure starts collapsed for each character.
// Loading, a failed load and a loaded empty list are three different things, and an unavailable
// list (not found or not permitted, indistinguishable by design) says nothing about parties.
export function CharacterParties({ campaignId, characterId }: CharacterPartiesProps) {
  const { state, refetch } = useAuthoringResource<CharacterPartiesData>(
    characterPartiesPath(campaignId, characterId),
  )

  if (state.kind === "loading") {
    return (
      <p className="campaign-context-panel__note">Loading parties…</p>
    )
  }
  if (state.kind === "error") {
    return (
      <p className="campaign-context-panel__note" role="status">
        Parties could not be loaded.{" "}
        <button
          type="button"
          className="campaign-context-panel__link-button"
          onClick={() => void refetch()}
        >
          Try again
        </button>
      </p>
    )
  }
  if (state.kind !== "ready") {
    return <p className="campaign-context-panel__note">Parties unavailable.</p>
  }

  const { items, can_open: canOpen } = state.data
  return (
    <details className="campaign-context-panel__parties">
      <summary>Parties ({items.length})</summary>
      {items.length === 0 ? (
        <p className="campaign-context-panel__note">No party memberships.</p>
      ) : (
        <ul className="campaign-context-panel__party-list">
          {items.map((party) => (
            <li key={party.party_id}>
              {canOpen ? (
                <Link
                  to={`/app/${encodeURIComponent(campaignId)}/parties/${encodeURIComponent(party.party_id)}`}
                >
                  {party.name}
                </Link>
              ) : (
                party.name
              )}
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}
