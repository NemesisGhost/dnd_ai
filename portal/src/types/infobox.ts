import type { ReactNode } from "react"

// Generic Wiki-style infobox model. Deliberately entity-agnostic: domain
// wrappers translate a specific record into this shape rather than teaching
// InfoBox about any one entity type.

export interface InfoBoxRow {
  label: string
  value: ReactNode
}

export interface InfoBoxSection {
  heading?: string
  rows: InfoBoxRow[]
}

export interface InfoBoxLink {
  label: string
  to: string
}

export interface InfoBoxImage {
  src: string
  alt: string
}

export interface InfoBoxProps {
  title: string
  subtitle?: string
  image?: InfoBoxImage
  status?: ReactNode
  sections: InfoBoxSection[]
  relatedLinks?: InfoBoxLink[]
}
