import {
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
} from "vitest"
import { HitPointsMeter } from "./HitPointsMeter"

describe("HitPointsMeter", () => {
    it("renders an accessible proportional value", () => {
        const { container } = render(
            <HitPointsMeter
                currentHitPoints={6}
                maximumHitPoints={12}
            />,
        )

        const meter = screen.getByRole("meter", {
            name: "Hit points",
        })

        expect(meter).toHaveAttribute(
            "aria-valuemin",
            "0",
        )
        expect(meter).toHaveAttribute(
            "aria-valuemax",
            "12",
        )
        expect(meter).toHaveAttribute(
            "aria-valuenow",
            "6",
        )
        expect(meter).toHaveAttribute(
            "aria-valuetext",
            "6 of 12 hit points",
        )

        const fill =
            container.querySelector<HTMLElement>(
                ".hit-points-meter__fill",
            )

        const filledLabel =
            container.querySelector<HTMLElement>(
                ".hit-points-meter__label--filled",
            )

        expect(fill?.style.width).toBe("50%")
        expect(filledLabel?.style.clipPath).toBe(
            "inset(0 50% 0 0)",
        )

        expect(
            screen.getAllByText("6 / 12"),
        ).toHaveLength(2)
    })

    it.each([
        {
            currentHitPoints: -2,
            maximumHitPoints: 10,
            expectedValue: "0",
            expectedWidth: "0%",
            expectedClip: "inset(0 100% 0 0)",
        },
        {
            currentHitPoints: 15,
            maximumHitPoints: 10,
            expectedValue: "10",
            expectedWidth: "100%",
            expectedClip: "inset(0 0% 0 0)",
        },
    ])(
        "clamps $currentHitPoints of $maximumHitPoints to the valid meter range",
        ({
            currentHitPoints,
            maximumHitPoints,
            expectedValue,
            expectedWidth,
            expectedClip,
        }) => {
            const { container } = render(
                <HitPointsMeter
                    currentHitPoints={currentHitPoints}
                    maximumHitPoints={maximumHitPoints}
                />,
            )

            const meter = screen.getByRole("meter", {
                name: "Hit points",
            })

            expect(meter).toHaveAttribute(
                "aria-valuenow",
                expectedValue,
            )

            const fill =
                container.querySelector<HTMLElement>(
                    ".hit-points-meter__fill",
                )

            const filledLabel =
                container.querySelector<HTMLElement>(
                    ".hit-points-meter__label--filled",
                )

            expect(fill?.style.width).toBe(expectedWidth)
            expect(filledLabel?.style.clipPath).toBe(
                expectedClip,
            )
        },
    )

    it("uses plain text when there is no valid maximum", () => {
        render(
            <HitPointsMeter
                currentHitPoints={4}
                maximumHitPoints={0}
            />,
        )

        expect(
            screen.queryByRole("meter"),
        ).not.toBeInTheDocument()

        expect(
            screen.getByText("4 / 0"),
        ).toBeInTheDocument()
    })
})