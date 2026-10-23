// @vitest-environment jsdom

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchTabs, workspaceFileView } from "./WorkbenchTabs";

describe("WorkbenchTabs", () => {
  it("renders fixed navigation and selects a file tab", () => {
    const select = vi.fn();
    render(
      <WorkbenchTabs
        activeView={null}
        files={[{ path: "reports/result.md" }]}
        onSelect={select}
        onCloseFile={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "Chat" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Files" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Skills" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Scheduled" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "result.md" }));
    expect(select).toHaveBeenCalledWith(workspaceFileView("reports/result.md"));
  });

  it("exposes unsaved state and closes the requested document", () => {
    const close = vi.fn();
    render(
      <WorkbenchTabs
        activeView={workspaceFileView("analysis.py")}
        files={[{ path: "analysis.py" }]}
        dirtyFiles={new Set(["analysis.py"])}
        onSelect={vi.fn()}
        onCloseFile={close}
      />
    );

    expect(screen.getByLabelText("Unsaved changes")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Close analysis.py" }));
    expect(close).toHaveBeenCalledWith("analysis.py");
  });
});
