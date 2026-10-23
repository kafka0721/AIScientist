import { promises as fs } from "fs";
import { homedir } from "os";
import { join } from "path";
import { NextRequest, NextResponse } from "next/server";
import { getWorkspaceDir, isCrossOrigin } from "@/lib/server/workspace";
import {
  hasWorkspaceSupervisor,
  normalizeProjectPath,
  requestWorkspaceSwitch,
  RUNTIME_DIR,
  touchProject,
} from "@/lib/server/projects";

const DEFAULT_PORT = 6174;
const CONFIG_PATH =
  process.env.WITAISCIENTIST_CONFIG_PATH || join(RUNTIME_DIR, "config.yaml");

async function backendPort(): Promise<number> {
  const env = process.env.WITAISCIENTIST_LANGGRAPH_DEV_PORT;
  if (env && /^\d+$/.test(env.trim())) return Number(env.trim());
  try {
    const yaml = await fs.readFile(CONFIG_PATH, "utf-8");
    const match = yaml.match(/^\s*langgraph_dev_port:\s*(\d+)\s*$/m);
    if (match) return Number(match[1]);
  } catch {
    // Missing config falls back to the conventional local port.
  }
  return DEFAULT_PORT;
}

async function isBackendReady(port: number): Promise<boolean> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/ok`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function POST(request: NextRequest) {
  if (isCrossOrigin(request)) {
    return NextResponse.json(
      { error: "Cross-origin request blocked." },
      { status: 403 }
    );
  }
  try {
    const body = (await request.json()) as { path?: unknown };
    if (typeof body.path !== "string") {
      return NextResponse.json(
        { error: "A folder path is required." },
        { status: 400 }
      );
    }
    const path = await normalizeProjectPath(body.path);
    const port = await backendPort();
    const current = await getWorkspaceDir().catch(() => null);
    if (current === path && (await isBackendReady(port))) {
      return NextResponse.json({
        project: await touchProject(path),
        active: path,
      });
    }
    if (!(await hasWorkspaceSupervisor())) {
      return NextResponse.json(
        {
          error:
            "This AIScientist backend was not started by a workspace-aware launcher. Restart it with start-webui.bat or ImagingSci WebUI.",
        },
        { status: 409 }
      );
    }

    await requestWorkspaceSwitch(path);
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      const active = await getWorkspaceDir().catch(() => null);
      if (active === path && (await isBackendReady(port))) {
        return NextResponse.json({
          project: await touchProject(path),
          active: path,
        });
      }
    }
    return NextResponse.json(
      {
        error:
          "The new workspace did not become ready in time. The previous workspace was kept when possible.",
      },
      { status: 504 }
    );
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Workspace switch failed.",
      },
      { status: 400 }
    );
  }
}
