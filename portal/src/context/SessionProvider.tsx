import type { PropsWithChildren } from "react"
import { useSessionBootstrap } from "../hooks/useSessionBootstrap"
import { SessionContext } from "./SessionContext"

export function SessionProvider({
  children,
}: PropsWithChildren) {
  const session = useSessionBootstrap()

  return (
    <SessionContext.Provider value={session}>
      {children}
    </SessionContext.Provider>
  )
}