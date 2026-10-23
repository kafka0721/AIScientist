import { NextRequest, NextResponse } from "next/server";
import { getWorkspaceDir, isCrossOrigin } from "@/lib/server/workspace";
import {
  addProject,
  hasWorkspaceSupervisor,
  listProjects,
  removeProject,
} from "@/lib/server/projects";

async function activeWorkspace(): Promise<string | null> {
  try {
    return await getWorkspaceDir();
  } catch {
    return null;
  }
}

export async function GET() {
  const active = await activeWorkspace();
  if (active) await addProject(active);
  return NextResponse.json({
    active,
    switchingSupported: await hasWorkspaceSupervisor(),
    projects: await listProjects(active),
  });
}

export async function POST(request: NextRequest) {
  if (isCrossOrigin(request)) {
    return NextResponse.json(
      { error: "Cross-origin request blocked." },
      { status: 403 }
    );
  }
  try {
    const body = (await request.json()) as { action?: unknown; path?: unknown };
    if (typeof body.path !== "string") {
      return NextResponse.json(
        { error: "A folder path is required." },
        { status: 400 }
      );
    }
    if (body.action === "remove") {
      await removeProject(body.path);
      return NextResponse.json({ ok: true });
    }
    if (body.action !== "add") {
      return NextResponse.json(
        { error: "Unknown project action." },
        { status: 400 }
      );
    }
    return NextResponse.json({ project: await addProject(body.path) });
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : "Project update failed.",
      },
      { status: 400 }
    );
  }
}
