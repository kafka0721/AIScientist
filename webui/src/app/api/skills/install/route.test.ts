import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";
import { installSkill } from "@/lib/server/skills";

vi.mock("@/lib/server/skills", () => ({ installSkill: vi.fn() }));

function request(url: string, origin?: string, site = "same-origin", body = { name: "paper-writing" }) {
  const headers = new Headers({ "Content-Type": "application/json", "Sec-Fetch-Site": site });
  if (origin !== undefined) headers.set("Origin", origin);
  return new NextRequest(`${url}/api/skills/install`, {
    method: "POST", headers, body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.mocked(installSkill).mockReset();
  vi.mocked(installSkill).mockResolvedValue({ files: 12 });
});

describe("skill installation origin validation", () => {
  it.each([
    ["http://localhost:4716", "http://127.0.0.1:4716"],
    ["http://127.0.0.1:4716", "http://localhost:4716"],
    ["http://127.0.0.1:4716", "http://127.0.0.1:4716"],
    ["http://localhost:4716", "http://localhost:4716"],
  ])("installs through the local UI: server %s, browser %s", async (url, origin) => {
    const response = await POST(request(url, origin));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, files: 12 });
    expect(installSkill).toHaveBeenCalledExactlyOnceWith("paper-writing");
  });

  it.each([
    ["https://example.com", "cross-site"],
    ["https://example.com", "same-origin"],
    ["http://localhost:4717", "same-site"],
    ["http://127.0.0.1:4717", "same-site"],
    ["https://127.0.0.1:4716", "same-origin"],
    ["http://localhost.evil.example:4716", "same-origin"],
    ["null", "same-origin"],
    ["invalid", "same-origin"],
    ["http://localhost:4716", "cross-site"],
    [undefined, "cross-site"],
  ])("rejects untrusted origin %s with fetch metadata %s", async (origin, site) => {
    const response = await POST(request("http://localhost:4716", origin, site));
    expect(response.status).toBe(403);
    expect(installSkill).not.toHaveBeenCalled();
  });

  it("preserves direct non-browser installation support", async () => {
    const response = await POST(request("http://localhost:4716", undefined, "none"));
    expect(response.status).toBe(200);
  });

  it("validates the body after accepting a local browser request", async () => {
    const response = await POST(request("http://localhost:4716", "http://127.0.0.1:4716", "same-origin", { name: "" }));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Missing skill name." });
    expect(installSkill).not.toHaveBeenCalled();
  });
});
