import type { RulesetListResponse } from "../types/worldAuthoring"
import { apiRequest } from "./http"

export const RULESETS_PATH = "/rulesets"

export function fetchRulesets(signal?: AbortSignal): Promise<RulesetListResponse> {
    return apiRequest<RulesetListResponse>("GET", RULESETS_PATH, { signal })
}
