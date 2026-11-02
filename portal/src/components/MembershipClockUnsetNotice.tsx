import { Link } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"

// Why current membership is not shown: the campaign has no clock, so who is a member "now" is
// undetermined (the server withholds it). It says nothing about which parties or members exist, so
// it can be shown wherever the server reported `clock_unset`. People who may set the clock
// (`canon.edit`, which the server re-checks) are pointed at the one place that does it; recording
// an in-world time elsewhere never sets campaign Now.
export function MembershipClockUnsetNotice({
    campaignId,
    className = "authoring-note",
    subject = "Current membership",
}: {
    campaignId: string
    className?: string
    subject?: string
}) {
    const canSetClock = useCampaignCapability(campaignId, "canon.edit")
    return (
        <p className={className} role="status">
            {subject} cannot be determined because the campaign time has not been set.
            {canSetClock ? (
                <>
                    {" "}
                    <Link to={`/app/${encodeURIComponent(campaignId)}`}>
                        Set the campaign time on Campaign Home
                    </Link>{" "}
                    (recording an in-world time does not set it).
                </>
            ) : null}
        </p>
    )
}
