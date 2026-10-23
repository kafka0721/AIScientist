// @vitest-environment jsdom

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectsHome } from "./ProjectsHome";

vi.mock("next/image", () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => (
    <img
      {...props}
      alt={props.alt || ""}
    />
  ),
}));

vi.mock("@/app/components/ThemeToggle", () => ({
  ThemeToggle: () => <button type="button">Theme</button>,
}));

vi.mock("@/app/components/HealthIndicator", () => ({
  HealthIndicator: () => <span>Connected</span>,
}));

describe("ProjectsHome", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads, filters, and opens registered projects", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          active: "D:\\research\\alpha",
          switchingSupported: true,
          projects: [
            {
              path: "D:\\research\\alpha",
              name: "alpha",
              addedAt: "2026-08-05T00:00:00.000Z",
              lastOpenedAt: "2026-08-05T00:00:00.000Z",
            },
            {
              path: "D:\\research\\beta",
              name: "beta",
              addedAt: "2026-08-04T00:00:00.000Z",
              lastOpenedAt: "2026-08-04T00:00:00.000Z",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    const open = vi.fn().mockResolvedValue(undefined);

    render(
      <ProjectsHome
        deploymentUrl="http://127.0.0.1:6174"
        onReconnect={vi.fn()}
        onOpenProject={open}
        onOpenSettings={vi.fn()}
      />
    );

    expect(screen.getByText("Imaging Scientist")).toBeDefined();
    expect(screen.queryByText("WITAIScientist")).toBeNull();
    expect(screen.queryByText("imaging_scientist")).toBeNull();
    expect(await screen.findByText("alpha")).toBeDefined();
    expect(screen.getByText("beta")).toBeDefined();
    fireEvent.change(screen.getAllByPlaceholderText("Search projects...")[0], {
      target: { value: "beta" },
    });
    expect(screen.queryByText("alpha")).toBeNull();
    fireEvent.click(screen.getByText("beta"));
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith("D:\\research\\beta")
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/projects", {
      cache: "no-store",
    });
  });
});
