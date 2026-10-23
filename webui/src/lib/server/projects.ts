import { randomUUID } from "crypto";
import { promises as fs } from "fs";
import { basename, dirname, isAbsolute, join, resolve } from "path";

export const RUNTIME_DIR =
  process.env.WITAISCIENTIST_RUNTIME_DIR ||
  join(process.cwd(), ".imaging-scientist-runtime");
// The backend owns the runtime directory above, including workspace switch
// coordination. The WebUI's optional project list belongs to the front-end and
// must not make the page unusable when a sandboxed Node process cannot write
// the user's home directory.
const PROJECTS_STATE_DIR = join(process.cwd(), ".webui-state");
const PROJECTS_PATH = join(PROJECTS_STATE_DIR, "projects.json");
export const WORKSPACE_SWITCH_PATH = join(RUNTIME_DIR, "workspace-switch.json");
const WORKSPACE_SUPERVISOR_PATH = join(
  RUNTIME_DIR,
  "workspace-supervisor.json"
);

export interface ProjectRecord {
  path: string;
  name: string;
  addedAt: string;
  lastOpenedAt: string;
}

interface ProjectFile {
  version: 1;
  projects: ProjectRecord[];
}

function isProjectRecord(value: unknown): value is ProjectRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.path === "string" &&
    typeof record.name === "string" &&
    typeof record.addedAt === "string" &&
    typeof record.lastOpenedAt === "string"
  );
}

async function readProjectFile(): Promise<ProjectFile> {
  try {
    const parsed = JSON.parse(await fs.readFile(PROJECTS_PATH, "utf-8")) as {
      projects?: unknown;
    };
    return {
      version: 1,
      projects: Array.isArray(parsed.projects)
        ? parsed.projects.filter(isProjectRecord)
        : [],
    };
  } catch {
    return { version: 1, projects: [] };
  }
}

async function writeProjectFile(projects: ProjectRecord[]): Promise<void> {
  await fs.mkdir(PROJECTS_STATE_DIR, { recursive: true });
  const temp = `${PROJECTS_PATH}.${randomUUID()}.tmp`;
  await fs.writeFile(
    temp,
    JSON.stringify({ version: 1, projects } satisfies ProjectFile, null, 2),
    "utf-8"
  );
  await fs.rename(temp, PROJECTS_PATH);
}

export async function normalizeProjectPath(input: string): Promise<string> {
  const value = input.trim();
  if (!value || value.length > 4096 || !isAbsolute(value)) {
    throw new Error("Choose an absolute folder path.");
  }
  const path = await fs.realpath(resolve(value));
  const stat = await fs.stat(path);
  if (!stat.isDirectory())
    throw new Error("The selected path is not a folder.");
  return path;
}

function recordFor(path: string, timestamp: string): ProjectRecord {
  return {
    path,
    name: basename(path) || path,
    addedAt: timestamp,
    lastOpenedAt: timestamp,
  };
}

async function defaultWorkspace(): Promise<string | null> {
  // The launcher provides the active workspace explicitly. When the WebUI is
  // opened on its own, fall back to the deployment's adjacent `data` folder.
  const candidate =
    process.env.WITAISCIENTIST_WORKSPACE_DIR ||
    resolve(process.cwd(), "..", "data");
  try {
    return await normalizeProjectPath(candidate);
  } catch {
    return null;
  }
}

export async function listProjects(
  activeWorkspace?: string | null
): Promise<ProjectRecord[]> {
  const file = await readProjectFile();
  const projects = [...file.projects];
  const defaultPath = await defaultWorkspace();
  if (defaultPath && !projects.some((project) => project.path === defaultPath)) {
    projects.push(recordFor(defaultPath, new Date().toISOString()));
  }
  if (
    activeWorkspace &&
    !projects.some((project) => project.path === activeWorkspace)
  ) {
    projects.push(recordFor(activeWorkspace, new Date().toISOString()));
  }
  return projects.sort((a, b) => b.lastOpenedAt.localeCompare(a.lastOpenedAt));
}

export async function addProject(input: string): Promise<ProjectRecord> {
  const path = await normalizeProjectPath(input);
  const file = await readProjectFile();
  const existing = file.projects.find((project) => project.path === path);
  if (existing) return existing;
  const project = recordFor(path, new Date().toISOString());
  await writeProjectFile([project, ...file.projects]);
  return project;
}

export async function touchProject(input: string): Promise<ProjectRecord> {
  const path = await normalizeProjectPath(input);
  const now = new Date().toISOString();
  const file = await readProjectFile();
  const existing = file.projects.find((project) => project.path === path);
  const project = existing
    ? { ...existing, name: basename(path) || path, lastOpenedAt: now }
    : recordFor(path, now);
  await writeProjectFile([
    project,
    ...file.projects.filter((item) => item.path !== path),
  ]);
  return project;
}

export async function removeProject(input: string): Promise<void> {
  const path = await normalizeProjectPath(input);
  const file = await readProjectFile();
  await writeProjectFile(
    file.projects.filter((project) => project.path !== path)
  );
}

export async function requestWorkspaceSwitch(path: string): Promise<void> {
  await fs.mkdir(RUNTIME_DIR, { recursive: true });
  const temp = `${WORKSPACE_SWITCH_PATH}.${randomUUID()}.tmp`;
  await fs.writeFile(
    temp,
    JSON.stringify({ workspace: path, requestedAt: new Date().toISOString() }),
    "utf-8"
  );
  await fs.rename(temp, WORKSPACE_SWITCH_PATH);
}

export async function hasWorkspaceSupervisor(): Promise<boolean> {
  try {
    const parsed = JSON.parse(
      await fs.readFile(WORKSPACE_SUPERVISOR_PATH, "utf-8")
    ) as { pid?: unknown };
    if (typeof parsed.pid !== "number" || parsed.pid <= 0) return false;
    process.kill(parsed.pid, 0);
    return true;
  } catch {
    return false;
  }
}

export async function listFolders(input?: string | null): Promise<{
  path: string;
  parent: string | null;
  entries: Array<{ name: string; path: string }>;
}> {
  // Some Windows environments allow Node to read USERPROFILE but deny
  // realpath() on it. Start at the WebUI working directory instead of making
  // the project picker unusable before the user chooses a folder.
  const initial = input?.trim() || process.cwd();
  if (!isAbsolute(initial)) throw new Error("Choose an absolute folder path.");
  const path = await fs.realpath(resolve(initial));
  const stat = await fs.stat(path);
  if (!stat.isDirectory())
    throw new Error("The selected path is not a folder.");
  const dirents = await fs.readdir(path, { withFileTypes: true });
  const entries = dirents
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
    .slice(0, 500)
    .map((entry) => ({ name: entry.name, path: join(path, entry.name) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const parent = dirname(path);
  return { path, parent: parent === path ? null : parent, entries };
}
