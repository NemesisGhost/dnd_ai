import { afterEach, expect, test, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

afterEach(() => vi.unstubAllGlobals());

test("uses the same-origin API route and an in-memory access token", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ready" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const request = createApiClient(() => ({ displayName: "GM", accessToken: "temporary-token" }));

  await expect(request<{ status: string }>("/readyz")).resolves.toEqual({ status: "ready" });
  const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(path).toBe("/api/readyz");
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer temporary-token");
  expect(init.credentials).toBe("same-origin");
});

test("normalizes the stable API error contract", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "forbidden", message: "Access denied." }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  const request = createApiClient(() => null);

  await expect(request("/campaigns/demo/summary")).rejects.toEqual(
    new ApiError(403, "forbidden", "Access denied."),
  );
});
