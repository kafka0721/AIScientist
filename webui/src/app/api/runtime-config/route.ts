import { NextRequest, NextResponse } from "next/server";
import { homedir } from "os";
import { join } from "path";
import { promises as fs } from "fs";

const DEFAULT_PORT = 6174;
const CONFIG_PATH =
  process.env.WITAISCIENTIST_CONFIG_PATH ||
  join(homedir(), ".config", "witaiscientist", "config.yaml");

async function resolveBackendUrl(): Promise<string> {
  const envPort = process.env.WITAISCIENTIST_LANGGRAPH_DEV_PORT;
  if (envPort && /^\d+$/.test(envPort.trim())) {
    return `http://127.0.0.1:${parseInt(envPort.trim(), 10)}`;
  }
  try {
    const yaml = await fs.readFile(CONFIG_PATH, "utf-8");
    const match = yaml.match(/^\s*langgraph_dev_port:\s*(\d+)\s*$/m);
    if (match) return `http://127.0.0.1:${parseInt(match[1], 10)}`;
  } catch {
    // Fall back to the backend's default port.
  }
  return `http://127.0.0.1:${DEFAULT_PORT}`;
}

async function proxy(request: NextRequest): Promise<NextResponse> {
  try {
    const backendUrl = await resolveBackendUrl();
    const init: RequestInit = {
      method: request.method,
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    };
    if (request.method === "PUT") init.body = await request.text();
    const response = await fetch(`${backendUrl}/api/runtime-config`, init);
    const body = await response.json().catch(() => null);
    return NextResponse.json(body ?? { error: "Invalid backend response." }, {
      status: response.status,
    });
  } catch {
    return NextResponse.json(
      { error: "The AIScientist backend is unavailable." },
      { status: 502 }
    );
  }
}

export async function GET(request: NextRequest) {
  return proxy(request);
}

export async function PUT(request: NextRequest) {
  return proxy(request);
}
