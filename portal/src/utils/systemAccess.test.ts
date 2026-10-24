import { describe, expect, it } from "vitest"
import {
    canGrantAdmin,
    canHostCampaigns,
    canManageAccounts,
    canManageSystemRoles,
} from "./systemAccess"

describe("system access helpers", () => {
    it("read only the server-computed global capabilities", () => {
        expect(canManageAccounts({ global_capabilities: ["accounts.manage"] })).toBe(true)
        expect(canManageSystemRoles({ global_capabilities: ["system_roles.manage"] })).toBe(true)
        expect(canGrantAdmin({ global_capabilities: ["system_roles.grant_admin"] })).toBe(true)
        expect(canHostCampaigns({ global_capabilities: ["campaign.host"] })).toBe(true)
    })

    it("deny by default, and one capability never implies another", () => {
        expect(canManageAccounts({})).toBe(false)
        expect(canManageAccounts({ global_capabilities: [] })).toBe(false)
        // An Administrator without the GM role cannot host campaigns, and vice versa.
        expect(canHostCampaigns({ global_capabilities: ["accounts.manage", "system_roles.manage"] })).toBe(false)
        expect(canManageAccounts({ global_capabilities: ["world.create", "campaign.host"] })).toBe(false)
        // Granting Administrator is its own switch.
        expect(canGrantAdmin({ global_capabilities: ["system_roles.manage"] })).toBe(false)
    })
})
