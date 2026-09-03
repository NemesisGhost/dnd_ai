import type { PropsWithChildren } from "react"
import { useCharacterPerspective } from "../hooks/useCharacterPerspective"
import { useSessionBootstrap } from "../hooks/useSessionBootstrap"
import { CharacterPerspectiveContext } from "./CharacterPerspectiveContext"
import { SessionContext } from "./SessionContext"

export function SessionProvider({
  children,
}: PropsWithChildren) {
  const session = useSessionBootstrap()

  const perspective = useCharacterPerspective(session)

  return (
    <SessionContext.Provider value={session}>
      <CharacterPerspectiveContext.Provider
        value={perspective}
      >
        {children}
      </CharacterPerspectiveContext.Provider>
    </SessionContext.Provider>
  )
}