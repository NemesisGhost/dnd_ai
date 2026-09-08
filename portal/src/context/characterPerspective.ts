import type { CampaignContext } from "../types/bootstrap"

export type RequestedCharacterId =
  | string
  | null
  | undefined

export function resolveSelectedCharacterId(
  campaign: CampaignContext,
  requestedCharacterId: RequestedCharacterId,
): string | null {
  const isAuthorized = (
    characterId: string | null | undefined,
  ): characterId is string =>
    characterId !== null &&
    characterId !== undefined &&
    campaign.character_perspectives.some(
      (character) =>
        character.character_id === characterId,
    )

  // Null is an explicit request for campaign-wide context.
  if (requestedCharacterId === null) {
    return null
  }

  if (isAuthorized(requestedCharacterId)) {
    return requestedCharacterId
  }

  const serverDefaultCharacterId =
    campaign.selected_character_id

  if (isAuthorized(serverDefaultCharacterId)) {
    return serverDefaultCharacterId
  }

  return null
}