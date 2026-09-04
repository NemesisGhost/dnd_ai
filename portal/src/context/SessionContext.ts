import {
  createContext,
  useContext,
} from "react"
import type {
  UseSessionBootstrapResult,
} from "../hooks/useSessionBootstrap"

export const SessionContext =
  createContext<UseSessionBootstrapResult | undefined>(
    undefined,
  )

export function useSession(): UseSessionBootstrapResult {
  const session = useContext(SessionContext)

  if (session === undefined) {
    throw new Error(
      "useSession must be used inside SessionProvider",
    )
  }

  return session
}