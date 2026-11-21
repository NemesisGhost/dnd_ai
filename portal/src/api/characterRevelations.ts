// The GM's list of one character's revelations. Only the public-profile page's Revelations section
// calls anything under this path.
const enc = encodeURIComponent

export const revelationsPath = (campaignId: string, characterId: string): string =>
    `/campaigns/${enc(campaignId)}/characters/${enc(characterId)}/revelations`
