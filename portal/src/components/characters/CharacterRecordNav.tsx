import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { useLocation } from "react-router"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import { pickCharactersReturnState } from "../../hooks/useCharactersBackPath"
import { pickWorldReturnState } from "../../hooks/useWorldBackPath"
import type { CharacterDetail } from "../../types/character"
import { characterKindLabel } from "../../utils/characterKind"
import { sectionsOf } from "../../utils/characterSections"
import { CharacterInventoryPanel } from "../InventoryPanels"
import { CharacterParties } from "../CharacterParties"
import { CharacterRelationshipsSection } from "../CharacterRelationshipsSection"
import { SectionNav } from "../staged/StagedNav"
import type { SectionDef } from "../staged/StagedNav"
import { useStagedNavigation } from "../staged/useStagedNavigation"

// Which page a character is being read on. Both show the same record with the same navigation:
// the Characters route (`/characters/:id`) opens on the sheet, the World route
// (`/world/character/:id`) opens on the details, and the other is one link away.
export type CharacterRoute = "sheet" | "world"

type SectionKey = "details" | "sheet" | "relationships" | "inventory" | "parties"

const STAGE = "record"
const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

// One character's record: a row of the sections the server says this caller may open, and the one
// shown. The page owning the route supplies its own main section (`main`: the sheet or the summary
// panels on the Characters route, the details panels on the World route); the rest are shared.
//
// - A section appears only when `character.sections` offers it, and is mounted, and requested,
//   only while it is the one shown. A deep link to a section the caller may not open is replaced by
//   the main section, the way any unknown `?section=` is.
// - Editors have the authoring links (Open in World, Relationships, Edit) in the Manage row and
//   their relationships in the World workspace, so their row here is Sheet, Inventory and Parties.
// - The selected perspective is never read or changed: visiting a character selects nothing.
export function CharacterRecordSections({
    campaignId,
    characterId,
    character,
    route,
    main,
}: {
    campaignId: string
    characterId: string
    character: CharacterDetail
    route: CharacterRoute
    main: ReactNode
}) {
    const sections = sectionsOf(character)
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state } = useLocation()
    const root = base(campaignId)
    const id = encodeURIComponent(characterId)

    const mainKey: SectionKey = route === "sheet" ? "sheet" : "details"
    // On the Characters route a caller without the full tier gets the summary panels where the
    // sheet would be; the entry says so instead of offering a sheet that is not theirs.
    const keys: SectionKey[] = [mainKey]
    if (!canEdit && sections.relationships) keys.push("relationships")
    if (sections.inventory) keys.push("inventory")
    if (sections.parties) keys.push("parties")

    const nav = useStagedNavigation<typeof STAGE, SectionKey>(
        keys.map((key) => ({ key, stage: STAGE })),
        mainKey,
        { ready: true },
    )

    const labels: Record<SectionKey, string> = {
        details: "Details",
        sheet: route === "sheet" && !sections.sheet ? "Summary" : "Sheet",
        relationships: "Relationships",
        inventory: "Inventory",
        parties: "Parties",
    }
    // The other route's main section is a link out, in its natural place in the row.
    const order: SectionKey[] = ["details", "sheet", "relationships", "inventory", "parties"]
    const outKey: SectionKey | null =
        route === "sheet" ? (canEdit || !sections.details ? null : "details") : sections.sheet ? "sheet" : null
    const listed = order.filter((key) => keys.includes(key) || key === outKey)
    const defs: SectionDef<SectionKey>[] = listed.map((key) => ({ key, label: labels[key], purpose: "" }))
    const hrefFor = (key: SectionKey): string => {
        if (key === outKey) return key === "details" ? `${root}/world/character/${id}` : `${root}/characters/${id}`
        return nav.sectionHref(key)
    }
    // Both return states ride along every link, so Back from either route lands where it came from.
    const linkState = {
        ...pickCharactersReturnState(campaignId, state),
        ...pickWorldReturnState(state),
    }

    // Move focus to the content when the section changes after arrival (a link, Back or Forward).
    const content = useRef<HTMLDivElement>(null)
    const lastSection = useRef(nav.section)
    useEffect(() => {
        if (lastSection.current === nav.section) return
        lastSection.current = nav.section
        const heading = content.current?.querySelector<HTMLElement>("h1")
        if (heading !== null && heading !== undefined) {
            if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1")
            heading.focus()
        } else {
            content.current?.focus()
        }
    }, [nav.section])

    return (
        <div className="character-record">
            <SectionNav
                ariaLabel="Character sections"
                sections={defs}
                current={nav.section}
                hrefFor={hrefFor}
                linkState={Object.keys(linkState).length === 0 ? undefined : linkState}
            />
            <div ref={content} tabIndex={-1} className="character-record__content">
                {nav.section === mainKey ? main : null}
                {nav.section !== mainKey ? (
                    <section aria-labelledby="character-record-heading">
                        <p className="character-sheet__eyebrow">{characterKindLabel(character.character_kind)}</p>
                        <h1 id="character-record-heading">{character.name}</h1>
                        {nav.section === "relationships" ? (
                            <CharacterRelationshipsSection campaignId={campaignId} characterId={characterId} />
                        ) : null}
                        {nav.section === "inventory" ? (
                            <section aria-labelledby="character-inventory-heading">
                                <h2 id="character-inventory-heading">Inventory</h2>
                                <CharacterInventoryPanel embedded campaignId={campaignId} characterId={characterId} />
                            </section>
                        ) : null}
                        {nav.section === "parties" ? (
                            <section aria-labelledby="character-parties-heading">
                                <h2 id="character-parties-heading">Parties</h2>
                                <CharacterParties open campaignId={campaignId} characterId={characterId} />
                            </section>
                        ) : null}
                    </section>
                ) : null}
            </div>
        </div>
    )
}
