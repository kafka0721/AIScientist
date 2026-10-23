import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";

const active = vi.hoisted(() => ({ workspace: "" }));
vi.mock("./workspace", () => ({ getWorkspaceDir: async () => active.workspace }));

let root: string;
let skills: typeof import("./skills");
const sha = "a".repeat(40);
const names = ["paper-writing", "research-survey", "experiment-craft", "paper-review"];
const markdown = (name: string) => `---
name: ${name}
description: >-
  Research guidance for
  ${name}.
metadata:
  version: "1.2.0"
---
# ${name}
Detailed instructions.
`;
const tree: { path: string; type: string; size?: number }[] = [
  ...names.map((name) => ({ path: `skills/${name}/SKILL.md`, type: "blob", size: 200 })),
  { path: "skills/paper-writing/references/example.txt", type: "blob", size: 10 },
  { path: "skills/assets/logo.png", type: "blob" },
  { path: "EvoScientist/skills/find-skills/SKILL.md", type: "blob" },
];

function remote({ treeFailure = false, rawFailure = false, truncated = false } = {}) {
  return vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url === "https://api.github.com/repos/EvoScientist/EvoSkills/commits/main") {
      return Response.json({ sha });
    }
    if (url === `https://api.github.com/repos/EvoScientist/EvoSkills/git/trees/${sha}?recursive=1`) {
      if (treeFailure) throw new TypeError("network unavailable");
      return Response.json({ tree, truncated });
    }
    if (url === `https://data.jsdelivr.com/v1/package/gh/EvoScientist/EvoSkills@${sha}/flat`) {
      return Response.json({ files: tree.map((blob) => ({ name: `/${blob.path}`, size: blob.size })) });
    }
    const rawPrefix = `https://raw.githubusercontent.com/EvoScientist/EvoSkills/${sha}/`;
    const cdnPrefix = `https://cdn.jsdelivr.net/gh/EvoScientist/EvoSkills@${sha}/`;
    if (url.startsWith(rawPrefix) || url.startsWith(cdnPrefix)) {
      if (rawFailure && url.startsWith(rawPrefix)) return new Response("unavailable", { status: 503 });
      const path = url.replace(rawPrefix, "").replace(cdnPrefix, "");
      return new Response(path.endsWith("SKILL.md") ? markdown(path.split("/")[1]) : "example");
    }
    throw new Error(`Unexpected catalog URL: ${url}`);
  }));
}

async function local(tier: string, name: string, md = markdown(name)) {
  await fs.mkdir(join(tier, name), { recursive: true });
  await fs.writeFile(join(tier, name, "SKILL.md"), md);
}

beforeEach(async () => {
  root = await fs.mkdtemp(join(tmpdir(), "aiscientist-skills-test-"));
  active.workspace = join(root, "workspace-a");
  vi.resetModules();
  vi.stubEnv("WITAISCIENTIST_DATA_DIR", join(root, "global"));
  vi.stubEnv("WITAISCIENTIST_BUILTIN_SKILLS_DIR", join(root, "builtin"));
  vi.stubEnv("WITAISCIENTIST_EXTRA_SKILLS_DIR", join(root, "extra"));
  vi.stubEnv("WITAISCIENTIST_HOST_USERPROFILE", "");
  vi.stubEnv("WITAISCIENTIST_SKILLS_DIR", "");
  skills = await import("./skills");
  remote();
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  // Only remove this test's generated directory under the OS temp root.
  if (!resolve(root).startsWith(resolve(tmpdir()) + sep)) throw new Error("Invalid cleanup root");
  await fs.rm(root, { recursive: true, force: true });
});

describe("research skill catalog", () => {
  it("lists research skills from EvoSkills, excluding directories without SKILL.md", async () => {
    const catalog = await skills.getCatalog();
    expect(catalog.map((s) => s.name).sort()).toEqual([...names].sort());
    expect(catalog.find((s) => s.name === "paper-writing")).toMatchObject({
      description: "Research guidance for paper-writing.", fileCount: 2, latestVersion: "1.2.0",
    });
  });

  it.each([{ treeFailure: true }, { truncated: true }])("falls back to a complete pinned CDN tree: %j", async (options) => {
    remote(options);
    expect(await skills.getCatalog()).toHaveLength(4);
    expect(fetch).toHaveBeenCalledWith(
      `https://data.jsdelivr.com/v1/package/gh/EvoScientist/EvoSkills@${sha}/flat`, expect.anything()
    );
  });

  it("uses the same CDN fallback for metadata, detail and installed files", async () => {
    remote({ rawFailure: true });
    expect((await skills.getCatalog())[0].description).toBeTruthy();
    expect(await skills.getSkillDetail("paper-writing")).toMatchObject({
      installed: false, body: "# paper-writing\nDetailed instructions.",
    });
    expect(await skills.installSkill("paper-writing")).toEqual({ files: 2 });
    expect(await fs.readFile(join(skills.SKILLS_INSTALL_DIR, "paper-writing", "SKILL.md"), "utf8"))
      .toBe(markdown("paper-writing"));
    const manifest = await fs.readFile(join(skills.SKILLS_INSTALL_DIR, ".installed.yaml"), "utf8");
    expect(manifest).toContain("source: EvoScientist/EvoSkills@skills/paper-writing");
    expect(manifest).toContain(`commit: ${sha}`);
    expect(await skills.getSkillDetail("paper-writing")).toMatchObject({ installed: true });
  });

  it("shows workspace, global, extra and built-in skills consistently after workspace switches", async () => {
    await local(join(active.workspace, "skills"), "paper-writing", markdown("workspace-copy"));
    await local(skills.SKILLS_INSTALL_DIR, "paper-writing");
    await local(join(root, "builtin"), "test-builtin");
    await local(join(root, "extra"), "test-extra");
    await fs.mkdir(join(skills.SKILLS_INSTALL_DIR, "paper-review"), { recursive: true });
    const { GET } = await import("../../app/api/skills/route");
    const first = (await (await GET()).json()).skills;
    expect(first.find((s: { name: string }) => s.name === "paper-writing")).toMatchObject({
      title: "workspace-copy", removable: false,
    });
    expect(first.map((s: { name: string }) => s.name)).toEqual(expect.arrayContaining(["test-extra", "test-builtin"]));
    expect(await skills.getSkillDetail("paper-writing")).toMatchObject({ title: "workspace-copy" });
    expect((await skills.getCatalog()).find((s) => s.name === "paper-review")?.installed).toBe(false);
    active.workspace = join(root, "workspace-b");
    expect(await skills.getSkillDetail("paper-writing")).toMatchObject({ title: "paper-writing" });
    expect((await (await GET()).json()).skills.find((s: { name: string }) => s.name === "paper-writing"))
      .toMatchObject({ title: "paper-writing", removable: true });
  });

  it("rejects installation of an asset directory", async () => {
    await expect(skills.installSkill("assets")).rejects.toThrow("not found");
  });

  it("parses CRLF YAML block descriptions and keeps unstructured markdown intact", async () => {
    expect(skills.parseFrontmatter(markdown("example").replaceAll("\n", "\r\n")))
      .toMatchObject({ name: "example", description: "Research guidance for example.", version: "1.2.0" });
    await local(join(root, "builtin"), "plain", "---\nA visual separator\n---\nSome instructions");
    expect((await skills.getSkillDetail("plain")).body).toBe("---\nA visual separator\n---\nSome instructions");
  });
});
