import { describe, expect, it } from "vitest"
import {
    ACCOUNTS_LIST_PATH,
    ACCOUNTS_NEW_PATH,
    accountsReturnState,
    accountsSearch,
    readAccountsFocus,
    readAccountsQuery,
    readAccountsReturn,
} from "./platformAccountsReturn"

describe("the platform accounts list address", () => {
    it("names the list and the creation route", () => {
        expect(ACCOUNTS_LIST_PATH).toBe("/platform/accounts")
        expect(ACCOUNTS_NEW_PATH).toBe("/platform/accounts/new")
    })

    it("reads a bounded q and nothing else", () => {
        expect(readAccountsQuery(new URLSearchParams("q=ali"))).toBe("ali")
        expect(readAccountsQuery(new URLSearchParams(""))).toBe("")
        expect(readAccountsQuery(new URLSearchParams("q=" + "a".repeat(200)))).toBe("a".repeat(200))
        expect(readAccountsQuery(new URLSearchParams("q=" + "a".repeat(201)))).toBe("")
        expect(readAccountsQuery(new URLSearchParams("q=a%00b"))).toBe("")
        expect(readAccountsQuery(new URLSearchParams("q=a%1Fb"))).toBe("")
        expect(readAccountsQuery(new URLSearchParams("q=a%7Fb"))).toBe("")
        expect(readAccountsQuery(new URLSearchParams("x=1"))).toBe("")
    })

    it("builds the search string for a query and none for an empty one", () => {
        expect(accountsSearch("")).toBe("")
        expect(accountsSearch("ali")).toBe("?q=ali")
        expect(accountsSearch("a b&c")).toBe("?q=a+b%26c")
    })
})

describe("the creation route's return state", () => {
    it("carries the list's own search", () => {
        expect(accountsReturnState("")).toEqual({ accountsReturn: "" })
        expect(accountsReturnState("ali")).toEqual({ accountsReturn: "?q=ali" })
    })

    it("reads back what it wrote", () => {
        expect(readAccountsReturn(accountsReturnState("ali"))).toBe("?q=ali")
        expect(readAccountsReturn(accountsReturnState("a b&c"))).toBe("?q=a+b%26c")
        expect(readAccountsReturn(accountsReturnState(""))).toBe("")
    })

    it.each([
        ["a missing state", undefined],
        ["null", null],
        ["a string", "?q=a"],
        ["a number", 7],
        ["a number value", { accountsReturn: 7 }],
        ["an object value", { accountsReturn: { q: "a" } }],
        ["an extra key", { accountsReturn: "?q=a&x=1" }],
        ["a key other than q", { accountsReturn: "?x=1" }],
        ["a repeated q", { accountsReturn: "?q=a&q=b" }],
        ["a protocol-relative address", { accountsReturn: "//evil.example" }],
        ["an absolute address", { accountsReturn: "https://evil.example/" }],
        ["a path", { accountsReturn: "/campaigns" }],
        ["a path with a query", { accountsReturn: "/campaigns?q=a" }],
        ["a value without the question mark", { accountsReturn: "q=a" }],
        ["an over-length value", { accountsReturn: "?q=" + "a".repeat(2000) }],
        ["an over-length q", { accountsReturn: "?q=" + "a".repeat(201) }],
        ["a control character", { accountsReturn: "?q=a%00b" }],
        ["a raw control character", { accountsReturn: "?q=a\u0001b" }],
    ])("gives an empty search for %s", (_label, state) => {
        expect(readAccountsReturn(state)).toBe("")
    })

    it("never lets the value choose the path", () => {
        // The destination is built from the constant path plus this validated search only.
        for (const value of ["?q=a", "", "//evil.example", "https://evil.example/", "/campaigns"]) {
            const search = readAccountsReturn({ accountsReturn: value })
            expect(search === "" || search.startsWith("?q=")).toBe(true)
        }
    })
})

describe("the list's focus marker", () => {
    it("is read only from the exact marker", () => {
        expect(readAccountsFocus({ accountsFocus: "create" })).toBe(true)
        expect(readAccountsFocus({ accountsFocus: "other" })).toBe(false)
        expect(readAccountsFocus({ accountsFocus: true })).toBe(false)
        expect(readAccountsFocus(null)).toBe(false)
        expect(readAccountsFocus(undefined)).toBe(false)
        expect(readAccountsFocus("create")).toBe(false)
    })
})
