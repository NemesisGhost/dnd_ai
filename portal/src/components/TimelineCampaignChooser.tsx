import { useEffect, useLayoutEffect, useRef } from "react"
import type { KeyboardEvent } from "react"
import { Link } from "react-router"
import { scopeRequest } from "../navigation/selectionTransitions"
import { useAnnounceOwned } from "./authoring/announcer"

export interface ChooserCampaign {
  id: string
  label: string
}

interface TimelineCampaignChooserProps {
  // The instruction's id: the Timeline select names it in its description while the chooser is open.
  instructionId: string
  timelineName: string
  // The caller's authorized campaigns on that timeline, in bootstrap order, derived from the CURRENT
  // bootstrap on every render by the panel: never a snapshot taken when the chooser opened.
  campaigns: readonly ChooserCampaign[]
  // Cancel and Escape: the panel closes the chooser and returns focus to the Timeline select.
  onCancel: () => void
  // Called as the chooser leaves the page while focus is still inside it (access changed under it), so the
  // panel can return focus to the select instead of letting it fall to the page.
  onClosedWithFocus: () => void
}

// The inline, non-modal campaign chooser (docs/UI_DESIGN.md §4.8.12, CN-1): a timeline the caller reaches
// through several of their campaigns opens none of them until the person picks one. It is not a dialog,
// it changes nothing by being open, and each link is the same departure the Campaign select makes (a new
// campaign task and the campaign selection note), so the departure guard, the arrival announcement and the
// destination focus are the ones every Infobox departure already has.
export function TimelineCampaignChooser({
  instructionId,
  timelineName,
  campaigns,
  onCancel,
  onClosedWithFocus,
}: TimelineCampaignChooserProps) {
  const groupRef = useRef<HTMLDivElement>(null)
  const instructionRef = useRef<HTMLParagraphElement>(null)
  const closedWithFocus = useRef(onClosedWithFocus)
  useLayoutEffect(() => {
    closedWithFocus.current = onClosedWithFocus
  })
  // A layout cleanup runs before the chooser's nodes leave the document, so focus is still readable.
  useLayoutEffect(() => {
    const group = groupRef.current
    return () => {
      if (group !== null && group.contains(document.activeElement)) closedWithFocus.current()
    }
  }, [])
  const focusedCampaign = useRef<string | null>(null)
  const announceOwned = useAnnounceOwned()
  // Held in a ref so a stand-in announcer (a new function each render) cannot make the message repeat.
  const announceRef = useRef(announceOwned)
  useLayoutEffect(() => {
    announceRef.current = announceOwned
  })
  const instruction = `Choose a campaign to open ${timelineName}`

  // Said once, politely, through the shell announcer, and withdrawn when the chooser closes.
  useEffect(() => announceRef.current(instruction), [instruction])

  // If the entry holding focus disappears because access changed, focus moves to the instruction rather
  // than falling to the page.
  useLayoutEffect(() => {
    const held = focusedCampaign.current
    if (held === null || campaigns.some((campaign) => campaign.id === held)) return
    focusedCampaign.current = null
    const active = document.activeElement
    if (active === null || active === document.body) {
      instructionRef.current?.focus()
    }
  }, [campaigns])

  function onKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Escape") {
      event.stopPropagation()
      event.preventDefault()
      onCancel()
    }
  }

  return (
    <div
      ref={groupRef}
      role="group"
      aria-labelledby={instructionId}
      className="campaign-context-panel__chooser"
      onKeyDown={onKeyDown}
    >
      <p
        id={instructionId}
        ref={instructionRef}
        tabIndex={-1}
        className="campaign-context-panel__chooser-instruction"
      >
        {instruction}
      </p>
      <ul className="campaign-context-panel__chooser-list">
        {campaigns.map((campaign) => {
          const request = scopeRequest(`/app/${encodeURIComponent(campaign.id)}/home`, "campaign", {
            level: "campaign",
            id: campaign.id,
          })
          return (
            <li key={campaign.id}>
              <Link
                to={request.to}
                state={request.state}
                onFocus={() => {
                  focusedCampaign.current = campaign.id
                }}
                onBlur={(event) => {
                  // A link that was removed (access changed) keeps its record, so focus can be recovered;
                  // a real blur forgets it.
                  if (event.currentTarget.isConnected && focusedCampaign.current === campaign.id) {
                    focusedCampaign.current = null
                  }
                }}
              >
                {campaign.label}
              </Link>
            </li>
          )
        })}
      </ul>
      <button type="button" className="campaign-context-panel__retry" onClick={onCancel}>
        Cancel
      </button>
    </div>
  )
}
