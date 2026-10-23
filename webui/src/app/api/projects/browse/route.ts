import { NextRequest, NextResponse } from "next/server";
import { isCrossOrigin } from "@/lib/server/workspace";
import { listFolders } from "@/lib/server/projects";

export async function GET(request: NextRequest) {
  if (isCrossOrigin(request)) {
    return NextResponse.json(
      { error: "Cross-origin request blocked." },
      { status: 403 }
    );
  }
  try {
    return NextResponse.json(
      await listFolders(request.nextUrl.searchParams.get("path"))
    );
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Could not open that folder.",
      },
      { status: 400 }
    );
  }
}
