// Server-only helpers for the official EvoSkills catalog + installing skills.
//
// Catalog source: the public EvoScientist/EvoSkills repo. We read its file tree
// once via the GitHub trees API (1 request, cached) and download individual
// skill files from raw.githubusercontent.com (which doesn't count against the
// API rate limit). Skills install into ~/.witaiscientist/skills/<name>/ (the
// GLOBAL tier imaging_scientist reads from). We also maintain that tier's
// .installed.yaml manifest so imaging_scientist's onboard/CLI stay in sync.

import { homedir } from "os";
import { dirname, join, resolve, sep } from "path";
import { promises as fs } from "fs";
import { randomUUID } from "crypto";
import { parse } from "yaml";
import { getWorkspaceDir } from "./workspace";

const REPO = "EvoScientist/EvoSkills";
const BRANCH = "main";
const SKILLS_PREFIX = "skills/";

/** imaging_scientist's global data dir — `~/.witaiscientist` by default (paths.py
 *  DATA_DIR), relocatable via WITAISCIENTIST_DATA_DIR, exactly like the backend. */
function globalDataDir(): string {
  const env = process.env.WITAISCIENTIST_DATA_DIR;
  if (env && env.trim()) {
    return env.startsWith("~") ? join(homedir(), env.slice(1)) : resolve(env);
  }
  return join(homedir(), ".witaiscientist");
}

/**
 * Where skills install: imaging_scientist's GLOBAL skills tier
 * (`DATA_DIR/skills` = `~/.witaiscientist/skills`), matching `install_skill()`'s
 * default global target. NOT `~/.config/witaiscientist/skills` — that's the
 * pre-migration legacy location (only config.yaml/mcp.yaml still live there).
 */
export const SKILLS_INSTALL_DIR = join(globalDataDir(), "skills");

/** Skill tiers owned by this WebUI and therefore safe for it to modify. */
export const WEBUI_MANAGED_SKILL_DIRS = [
  SKILLS_INSTALL_DIR,
  join(homedir(), ".config", "witaiscientist", "skills"),
];

/**
 * `uv run ImagingSci onboard` normally writes under the real Windows profile,
 * while the production WebUI deliberately overrides USERPROFILE to keep its
 * own state inside the project. The launcher passes the original profile here
 * so those skills remain visible without becoming WebUI-managed files.
 */
function terminalOnboardSkillsDir(): string | null {
  const profile = process.env.WITAISCIENTIST_HOST_USERPROFILE?.trim();
  return profile ? join(resolve(profile), ".witaiscientist", "skills") : null;
}

function deploymentSkillsDir(): string {
  // The local launcher mirrors pre-existing host skills here so a sandboxed
  // Node process never needs to traverse the user's profile directory.
  return resolve(process.cwd(), "..", ".local-home", ".witaiscientist", "skills");
}

/** Resolve each request so switching the active project also switches skills. */
export async function getSkillDirs(): Promise<string[]> {
  const workspace = await getWorkspaceDir().catch(() => null);
  const dirs = [
    process.env.WITAISCIENTIST_SKILLS_DIR || (workspace && join(workspace, "skills")),
    ...WEBUI_MANAGED_SKILL_DIRS,
    process.env.WITAISCIENTIST_EXTRA_SKILLS_DIR,
    terminalOnboardSkillsDir(),
    deploymentSkillsDir(),
    process.env.WITAISCIENTIST_BUILTIN_SKILLS_DIR,
    // Development runs in webui/; the standalone server changes cwd to dist/.
    resolve(process.cwd(), "..", "imaging_scientist", "skills"),
    resolve(process.cwd(), "..", "..", "imaging_scientist", "skills"),
  ].filter((dir): dir is string => !!dir).map((dir) =>
    dir.startsWith("~") ? join(homedir(), dir.slice(1)) : resolve(dir)
  );
  return [...new Set(dirs)];
}

// Install guards.
const MAX_SKILL_FILES = 300;
const MAX_SKILL_BYTES = 25 * 1024 * 1024;

const GITHUB_HEADERS = {
  Accept: "application/vnd.github+json",
  // GitHub rejects API requests without a User-Agent.
  "User-Agent": "witaiscientist-webui",
};

export interface CatalogSkill {
  /** Directory name in the repo (the install identity), e.g. "paper-writing". */
  name: string;
  /** SKILL.md frontmatter name, falls back to the dir name. */
  title: string;
  description: string;
  fileCount: number;
  installed: boolean;
  /** Whether the installed copy belongs to a directory managed by this WebUI. */
  removable: boolean;
  /** metadata.version from the upstream SKILL.md (undefined if absent). */
  latestVersion?: string;
  /** metadata.version of the locally-installed SKILL.md (undefined if absent). */
  installedVersion?: string;
  /** True when installed and the upstream version is strictly newer. */
  updateAvailable: boolean;
}

/** Per-skill source recorded in .installed.yaml: the `owner/repo@path` shorthand
 *  with path = `skills/<name>`, so imaging_scientist tracks each skill's provenance
 *  (and its commit-based update check) individually rather than as one pack. */
function manifestSource(name: string): string {
  return `${REPO}@${SKILLS_PREFIX}${name}`;
}

interface TreeBlob {
  path: string;
  type: "blob" | "tree" | string;
  size?: number;
}

interface JsDelivrFlatFile {
  name?: string;
  size?: number;
}

/** A skill name must be a single safe path segment. Matches imaging_scientist's
 *  convention (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) — also blocks traversal and odd
 *  manifest keys. */
export function isValidSkillName(name: string): boolean {
  return (
    name.length <= 128 &&
    /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name) &&
    !name.includes("..")
  );
}

/** Split a SKILL.md into its frontmatter block and the body. The closing `---`
 *  must be its own full line (CRLF-tolerant); returns frontmatter=null when
 *  there's no delimited block (so a body that merely opens with a `---` rule
 *  isn't mistaken for frontmatter). */
function splitFrontmatter(md: string): {
  frontmatter: string | null;
  body: string;
} {
  const m = md.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  if (!m) return { frontmatter: null, body: md.trim() };
  return { frontmatter: m[1], body: md.slice(m[0].length).trim() };
}

function parseFields(fm: string): {
  name?: string;
  description?: string;
  version?: string;
} {
  try {
    const data = parse(fm);
    if (!data || typeof data !== "object") return {};
    const scalar = (value: unknown) =>
      typeof value === "string" || typeof value === "number"
        ? String(value).trim() : undefined;
    return {
      name: scalar(data.name),
      description: scalar(data.description),
      version: scalar(data.metadata?.version),
    };
  } catch {
    return {};
  }
}

export function parseFrontmatter(md: string): {
  name?: string;
  description?: string;
  version?: string;
} {
  const { frontmatter } = splitFrontmatter(md);
  return frontmatter ? parseFields(frontmatter) : {};
}

/** Compare dotted versions ("1.2.3"). Returns 1 if a>b, -1 if a<b, 0 if equal
 *  or unparseable. Tolerant of differing segment counts and non-numeric tails. */
function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map((s) => parseInt(s, 10));
  const pb = b.split(".").map((s) => parseInt(s, 10));
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (Number.isNaN(x) || Number.isNaN(y)) return 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

/** Read the locally-installed SKILL.md version for `name`, across the tiers. */
async function readInstalledVersion(name: string): Promise<string | undefined> {
  for (const dir of await getSkillDirs()) {
    try {
      const md = await fs.readFile(join(dir, name, "SKILL.md"), "utf-8");
      return parseFrontmatter(md).version;
    } catch {
      // not in this tier
    }
  }
  return undefined;
}

function rawUrl(ref: string, repoPath: string): string {
  return `https://raw.githubusercontent.com/${REPO}/${ref}/${repoPath}`;
}

async function fetchSkillFile(ref: string, repoPath: string): Promise<Response> {
  let failure: unknown;
  for (const url of [
    rawUrl(ref, repoPath),
    `https://cdn.jsdelivr.net/gh/${REPO}@${ref}/${repoPath}`,
  ]) {
    try {
      const res = await fetch(url, {
        headers: GITHUB_HEADERS,
        signal: AbortSignal.timeout(12000),
      });
      if (res.ok) return res;
      failure = new Error(`Failed to download ${repoPath} (${res.status}).`);
    } catch (error) {
      failure = error;
    }
  }
  throw failure;
}

const SHA_RE = /^[0-9a-f]{7,40}$/;

// A snapshot of the repo pinned to ONE ref (the branch-head commit SHA when
// resolvable, else the branch name). Catalog + install share it, so the file
// list, the raw downloads, and the recorded commit all refer to the SAME
// revision — the branch can't move out from under a single operation. Cached.
let snapshotCache: { at: number; ref: string; tree: TreeBlob[] } | null = null;
const TREE_TTL_MS = 5 * 60 * 1000;

/** Resolve the branch to its head commit SHA, falling back to the branch name. */
async function resolveRef(): Promise<string> {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${REPO}/commits/${BRANCH}`,
      { headers: GITHUB_HEADERS, signal: AbortSignal.timeout(10000) }
    );
    if (res.ok) {
      const data = (await res.json()) as { sha?: string };
      if (typeof data.sha === "string" && SHA_RE.test(data.sha))
        return data.sha;
    }
  } catch {
    // fall back to the branch name below
  }
  return BRANCH;
}

/**
 * GitHub's unauthenticated REST API allows only 60 requests per hour per IP.
 * jsDelivr exposes the same public GitHub tree without consuming that quota.
 * Its flat listing contains files only, which is exactly what the catalog uses.
 */
async function getSnapshotFromJsDelivr(ref: string): Promise<TreeBlob[]> {
  const res = await fetch(
    `https://data.jsdelivr.com/v1/package/gh/${REPO}@${ref}/flat`,
    { signal: AbortSignal.timeout(15000) }
  );
  if (!res.ok) {
    throw new Error(`jsDelivr ${res.status}`);
  }
  const data = (await res.json()) as { files?: JsDelivrFlatFile[] };
  if (!Array.isArray(data.files)) {
    throw new Error("Unexpected jsDelivr catalog response.");
  }
  return data.files.flatMap((file) => {
    if (typeof file.name !== "string" || !file.name.startsWith("/")) {
      return [];
    }
    return [{ path: file.name.slice(1), type: "blob", size: file.size }];
  });
}

async function getRepoSnapshot(
  force = false
): Promise<{ ref: string; tree: TreeBlob[] }> {
  if (!force && snapshotCache && Date.now() - snapshotCache.at < TREE_TTL_MS) {
    return { ref: snapshotCache.ref, tree: snapshotCache.tree };
  }
  const ref = await resolveRef();
  let tree: TreeBlob[];
  try {
    const res = await fetch(
      `https://api.github.com/repos/${REPO}/git/trees/${ref}?recursive=1`,
      { headers: GITHUB_HEADERS, signal: AbortSignal.timeout(10000) }
    );
    if (!res.ok) throw new Error(`GitHub ${res.status}`);
    const data = (await res.json()) as { tree?: TreeBlob[]; truncated?: boolean };
    if (!Array.isArray(data.tree) || data.truncated) {
      throw new Error("Incomplete response from the skills catalog.");
    }
    tree = data.tree;
  } catch {
    tree = await getSnapshotFromJsDelivr(ref);
  }
  snapshotCache = { at: Date.now(), ref, tree };
  return { ref, tree };
}

/** The commit to record in the manifest — the snapshot ref iff it's a SHA. */
function commitFromRef(ref: string): string | null {
  return ref !== BRANCH && SHA_RE.test(ref) ? ref : null;
}

// ---------------------------------------------------------------------------
// .installed.yaml manifest (imaging_scientist's per-tier skill registry)
//
// Schema: { <name>: { source: <str>, commit?: <sha> } }, written by imaging_scientist
// via `yaml.safe_dump(sort_keys=True)`. We read/merge/write the same shape so
// onboard's ✓ indicator + commit-based "update available" stay consistent.
// ---------------------------------------------------------------------------

type ManifestEntry = { source: string; commit?: string };
type Manifest = Record<string, ManifestEntry>;

function manifestPath(): string {
  return join(SKILLS_INSTALL_DIR, ".installed.yaml");
}

/** Minimal parser for the flat 2-level manifest (name → {source, commit}). */
function parseManifest(text: string): Manifest {
  const out: Manifest = {};
  let current: string | null = null;
  for (const line of text.split("\n")) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    if (/^\S/.test(line)) {
      const m = line.match(/^(\S[^:]*?):\s*$/);
      current = m ? m[1].trim() : null;
      if (current) out[current] = { source: "" };
    } else if (current) {
      const m = line.match(/^\s+([A-Za-z_]+)\s*:\s*(.+?)\s*$/);
      if (m) {
        const value = m[2].replace(/^["']|["']$/g, "").trim();
        if (m[1] === "source") out[current].source = value;
        else if (m[1] === "commit") out[current].commit = value;
      }
    }
  }
  // Drop entries without a source — matches imaging_scientist's loader leniency.
  for (const k of Object.keys(out)) if (!out[k].source) delete out[k];
  return out;
}

async function readManifest(): Promise<Manifest> {
  try {
    return parseManifest(await fs.readFile(manifestPath(), "utf-8"));
  } catch {
    return {};
  }
}

/** Emit matching `yaml.safe_dump(sort_keys=True)`: names sorted, inner keys
 *  sorted (commit before source), values unquoted (safe for our inputs). */
function emitManifest(m: Manifest): string {
  const names = Object.keys(m).sort();
  if (names.length === 0) return "{}\n";
  let out = "";
  for (const name of names) {
    out += `${name}:\n`;
    if (m[name].commit) out += `  commit: ${m[name].commit}\n`;
    out += `  source: ${m[name].source}\n`;
  }
  return out;
}

async function writeManifest(m: Manifest): Promise<void> {
  const path = manifestPath();
  const tmp = `${path}.${randomUUID()}.tmp`;
  await fs.mkdir(SKILLS_INSTALL_DIR, { recursive: true });
  await fs.writeFile(tmp, emitManifest(m), { mode: 0o600 });
  await fs.rename(tmp, path);
}

async function recordInstall(
  name: string,
  commit: string | null
): Promise<void> {
  const manifest = await readManifest();
  const source = manifestSource(name);
  manifest[name] = commit ? { source, commit } : { source };
  await writeManifest(manifest);
}

/** Remove a skill's manifest entry (used by uninstall). No-op if absent. */
export async function recordUninstall(name: string): Promise<void> {
  const manifest = await readManifest();
  if (name in manifest) {
    delete manifest[name];
    await writeManifest(manifest);
  }
}

async function listInstalledSkills(): Promise<Map<string, boolean>> {
  const skills = new Map<string, boolean>();
  for (const dir of await getSkillDirs()) {
    try {
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const e of entries) {
        if (e.isDirectory() && !e.name.startsWith(".")) {
          // First match wins because directories are ordered by precedence.
          if (!skills.has(e.name)) {
            try {
              await fs.access(join(dir, e.name, "SKILL.md"));
              skills.set(e.name, WEBUI_MANAGED_SKILL_DIRS.includes(dir));
            } catch {
              // A directory without SKILL.md is not an installed skill.
            }
          }
        }
      }
    } catch {
      // dir doesn't exist — skip
    }
  }
  return skills;
}

/** Blobs that live under `skills/<name>/`, keyed by skill dir name. */
function groupSkillBlobs(tree: TreeBlob[]): Map<string, TreeBlob[]> {
  const byName = new Map<string, TreeBlob[]>();
  for (const item of tree) {
    if (item.type !== "blob" || !item.path.startsWith(SKILLS_PREFIX)) continue;
    const rest = item.path.slice(SKILLS_PREFIX.length);
    const slash = rest.indexOf("/");
    if (slash <= 0) continue; // a file directly under skills/ (e.g. README) — not a skill
    const name = rest.slice(0, slash);
    if (!isValidSkillName(name)) continue;
    (byName.get(name) ?? byName.set(name, []).get(name)!).push(item);
  }
  return new Map([...byName].filter(([name, blobs]) =>
    blobs.some((blob) => blob.path === `${SKILLS_PREFIX}${name}/SKILL.md`)
  ));
}

export async function getCatalog(force = false): Promise<CatalogSkill[]> {
  const [{ ref, tree }, installed] = await Promise.all([
    getRepoSnapshot(force),
    listInstalledSkills(),
  ]);
  const byName = groupSkillBlobs(tree);

  const skills = await Promise.all(
    [...byName.entries()].map(async ([name, blobs]) => {
      let title = name;
      let description = "";
      let latestVersion: string | undefined;
      const skillMd = blobs.find(
        (b) => b.path === `${SKILLS_PREFIX}${name}/SKILL.md`
      );
      if (skillMd) {
        try {
          const md = await (await fetchSkillFile(ref, skillMd.path)).text();
          const fm = parseFrontmatter(md);
          title = fm.name || name;
          description = fm.description || "";
          latestVersion = fm.version;
        } catch {
          // best-effort metadata
        }
      }
      const isInstalled = installed.has(name);
      const removable = installed.get(name) ?? false;
      const installedVersion = isInstalled
        ? await readInstalledVersion(name)
        : undefined;
      const updateAvailable =
        isInstalled &&
        !!latestVersion &&
        !!installedVersion &&
        compareVersions(latestVersion, installedVersion) > 0;
      return {
        name,
        title,
        description,
        fileCount: blobs.length,
        installed: isInstalled,
        removable,
        latestVersion,
        installedVersion,
        updateAvailable,
      } satisfies CatalogSkill;
    })
  );

  return skills.sort((a, b) => a.title.localeCompare(b.title));
}

export interface SkillDetail {
  name: string;
  title: string;
  description: string;
  version?: string;
  /** SKILL.md content with the frontmatter block stripped. */
  body: string;
  installed: boolean;
}

/** Full SKILL.md for one skill — the locally-installed copy if present (what the
 *  agent actually uses), else the upstream version at the pinned ref. */
export async function getSkillDetail(name: string): Promise<SkillDetail> {
  if (!isValidSkillName(name)) throw new Error("Invalid skill name.");

  let md: string | undefined;
  let installed = false;
  for (const dir of await getSkillDirs()) {
    try {
      // Canonicalize and confirm the SKILL.md stays inside the tier — a
      // symlinked skill dir / file must not read arbitrary files off disk.
      const real = await fs.realpath(join(dir, name, "SKILL.md"));
      const root = await fs.realpath(dir);
      if (real !== root && !real.startsWith(root + sep)) continue;
      md = await fs.readFile(real, "utf-8");
      installed = true;
      break;
    } catch {
      // not in this tier, or a broken/escaping symlink
    }
  }
  if (md === undefined) {
    const { ref, tree } = await getRepoSnapshot();
    const skillMd = tree.find(
      (t) => t.type === "blob" && t.path === `${SKILLS_PREFIX}${name}/SKILL.md`
    );
    if (!skillMd) throw new Error(`Skill "${name}" was not found.`);
    const res = await fetchSkillFile(ref, skillMd.path);
    md = await res.text();
  }

  // Strip the frontmatter block only when it's a genuine, positively-parsed
  // block — never eat body content that merely opens with a `---` rule.
  const { frontmatter, body: rawBody } = splitFrontmatter(md);
  const fm = frontmatter ? parseFields(frontmatter) : {};
  const isRealFrontmatter =
    frontmatter !== null &&
    (fm.name != null || fm.description != null || fm.version != null);
  return {
    name,
    title: fm.name || name,
    description: fm.description || "",
    version: fm.version,
    body: isRealFrontmatter ? rawBody : md.trim(),
    installed,
  };
}

/** Download every file of `skills/<name>/` into the install dir, atomically. */
export async function installSkill(name: string): Promise<{ files: number }> {
  if (!isValidSkillName(name)) throw new Error("Invalid skill name.");

  const { ref, tree } = await getRepoSnapshot();
  const prefix = `${SKILLS_PREFIX}${name}/`;
  const blobs = tree.filter(
    (t) => t.type === "blob" && t.path.startsWith(prefix)
  );
  if (!blobs.some((blob) => blob.path === `${prefix}SKILL.md`)) {
    throw new Error(`Skill "${name}" was not found in the catalog.`);
  }
  if (blobs.length > MAX_SKILL_FILES) {
    throw new Error("This skill has too many files to install.");
  }
  const totalBytes = blobs.reduce((sum, b) => sum + (b.size ?? 0), 0);
  if (totalBytes > MAX_SKILL_BYTES) {
    throw new Error("This skill is too large to install.");
  }

  const installRoot = resolve(SKILLS_INSTALL_DIR);
  const destRoot = resolve(installRoot, name);
  if (destRoot !== join(installRoot, name)) {
    throw new Error("Invalid skill name.");
  }

  // Download to a temp dir (a dotfile, so it never shows as a skill mid-install),
  // then swap atomically. Roll back the temp dir on any failure.
  const tmpRoot = join(installRoot, `.installing-${name}-${randomUUID()}`);
  try {
    await fs.mkdir(tmpRoot, { recursive: true });
    for (const blob of blobs) {
      const rel = blob.path.slice(prefix.length);
      const target = resolve(tmpRoot, rel);
      if (target !== tmpRoot && !target.startsWith(tmpRoot + sep)) {
        throw new Error("Invalid file path in skill.");
      }
      const res = await fetchSkillFile(ref, blob.path);
      const buf = Buffer.from(await res.arrayBuffer());
      await fs.mkdir(dirname(target), { recursive: true });
      await fs.writeFile(target, buf);
    }
    // Replace any existing install, then move the fresh copy into place.
    await fs.rm(destRoot, { recursive: true, force: true });
    await fs.mkdir(installRoot, { recursive: true });
    await fs.rename(tmpRoot, destRoot);
  } catch (error) {
    await fs.rm(tmpRoot, { recursive: true, force: true }).catch(() => {});
    throw error;
  }

  // Record provenance in .installed.yaml so imaging_scientist's onboard/CLI see the
  // skill as installed (with the pinned commit for its update detection — the
  // SAME revision the files came from). Best-effort: a manifest failure must not
  // fail an otherwise-good install.
  try {
    await recordInstall(name, commitFromRef(ref));
  } catch {
    // ignore manifest write errors
  }

  return { files: blobs.length };
}
