import { CampaignLayout } from "./CampaignLayout"
import {
  AuthenticatedSessionBoundary,
} from "./AuthenticatedSessionBoundary"

export function CampaignSessionBoundary() {
  return (
    <AuthenticatedSessionBoundary>
      {(bootstrap) => (
        <CampaignLayout bootstrap={bootstrap} />
      )}
    </AuthenticatedSessionBoundary>
  )
}