import { createContext, useContext } from "react"

interface CharacterPerspectiveContextValue {
  getSelectedCharacterId: (
    campaignId: string,
  ) => string | null

  selectCharacter: (
    campaignId: string,
    characterId: string | null,
  ) => void

  /** Synchronizes an authorized-looking character id carried in a URL
   * (e.g. a Knowledge detail link's `character_id` query parameter) into
   * the visible selected perspective, without the bootstrap reload
   * `selectCharacter` triggers for an explicit user selection. No-ops for
   * an id that isn't in the current bootstrap's authorized
   * `character_perspectives` — the request itself stays server-authorized
   * regardless of what this updates. Optional because most consumers of
   * this context never need it. */
  syncCharacterFromUrl?: (
    campaignId: string,
    characterId: string,
  ) => void
}

export const CharacterPerspectiveContext =
  createContext<
    CharacterPerspectiveContextValue | undefined
  >(undefined)

export function usePerspective():
  CharacterPerspectiveContextValue {
  const perspective = useContext(
    CharacterPerspectiveContext,
  )

  if (perspective === undefined) {
    throw new Error(
      "usePerspective must be used inside SessionProvider",
    )
  }

  return perspective
}