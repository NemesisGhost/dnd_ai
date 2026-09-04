import type { PropsWithChildren } from "react"
import { useMatch } from "react-router"
import { SessionProvider } from "./SessionProvider"

export function RouteSessionProvider({
    children,
}: PropsWithChildren) {
    const campaignMatch = useMatch("/app/:campaignId/*")

    const campaignId = campaignMatch?.params.campaignId

    const sessionScope =
        campaignId === undefined
            ? "outside-campaign"
            : `campaign:${campaignId}`

    return (
        <SessionProvider key={sessionScope}>
            {children}
        </SessionProvider>
    )
}