// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useCollapseAgentActions } from "./uiSettings";

describe("UI settings storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("uses the default when localStorage cannot be read", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage denied");
    });

    const { result } = renderHook(() => useCollapseAgentActions());
    expect(result.current.value).toBe(true);
  });

  it("updates in memory when localStorage cannot be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage denied");
    });
    const { result } = renderHook(() => useCollapseAgentActions());

    act(() => result.current.setValue(false));
    expect(result.current.value).toBe(false);
  });
});
