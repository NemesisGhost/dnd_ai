// The reader route behind the character page's Relationships section. Campaign and character come
// from the address; the server resolves the world, timeline and effective time itself.
export const characterRelationshipsPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/relationships`
