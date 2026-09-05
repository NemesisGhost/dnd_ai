interface HitPointsMeterProps {
    currentHitPoints: number
    maximumHitPoints: number
}

export function HitPointsMeter({
    currentHitPoints,
    maximumHitPoints,
}: HitPointsMeterProps) {
    if (maximumHitPoints <= 0) {
        return (
            <span className="hit-points-meter__fallback">
                {currentHitPoints} / {maximumHitPoints}
            </span>
        )
    }

    const meterValue = Math.min(
        maximumHitPoints,
        Math.max(0, currentHitPoints),
    )

    const percentRemaining =
        (meterValue / maximumHitPoints) * 100

    const unfilledPercent = 100 - percentRemaining

    return (
        <div
            className="hit-points-meter"
            role="meter"
            aria-label="Hit points"
            aria-valuemin={0}
            aria-valuemax={maximumHitPoints}
            aria-valuenow={meterValue}
            aria-valuetext={`${currentHitPoints} of ${maximumHitPoints} hit points`}
        >
            <div
                className="hit-points-meter__fill"
                style={{
                    width: `${percentRemaining}%`,
                }}
                aria-hidden="true"
            />

            <span
                className="
          hit-points-meter__label
          hit-points-meter__label--unfilled
        "
                aria-hidden="true"
            >
                {currentHitPoints} / {maximumHitPoints}
            </span>

            <span
                className="
          hit-points-meter__label
          hit-points-meter__label--filled
        "
                style={{
                    clipPath: `inset(0 ${unfilledPercent}% 0 0)`,
                }}
                aria-hidden="true"
            >
                {currentHitPoints} / {maximumHitPoints}
            </span>
        </div>
    )
}