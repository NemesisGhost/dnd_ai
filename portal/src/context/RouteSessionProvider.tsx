import { useContext } from "react"
import type { PropsWithChildren } from "react"
import { useMatch } from "react-router"
import { SelectedContextProvider } from "../navigation/SelectedContextProvider"
import { SelectedContextStoreContext } from "../navigation/selectedContextStore"
import { SessionProvider } from "./SessionProvider"

export function RouteSessionProvider({
    children,
}: PropsWithChildren) {
    const campaignMatch = useMatch("/app/:campaignId/*")
    const providedAbove = useContext(SelectedContextStoreContext) !== null

    const campaignId = campaignMatch?.params.campaignId

    const sessionScope =
        campaignId === undefined
            ? "outside-campaign"
            : `campaign:${campaignId}`

    // The selection sits above the scope-keyed session, so the remount a campaign change causes never
    // drops it. main.tsx provides the tab's store; a tree rendered without it gets one here.
    const session = (
        <SessionProvider key={sessionScope}>
            {children}
        </SessionProvider>
    )
    return providedAbove ? session : <SelectedContextProvider>{session}</SelectedContextProvider>
}
