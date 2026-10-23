// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  configFromBackendStatus,
  DEFAULT_ASSISTANT_ID,
  getConfig,
  saveConfig,
} from "./config";

describe("deployment config storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("treats an unavailable localStorage as unconfigured", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage denied");
    });

    expect(getConfig()).toBeNull();
  });

  it("keeps the current session usable when config persistence fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage denied");
    });

    expect(() =>
      saveConfig({
        deploymentUrl: "http://127.0.0.1:6174",
        assistantId: DEFAULT_ASSISTANT_ID,
      })
    ).not.toThrow();
  });

  it("creates a browser connection from the local backend status", () => {
    expect(
      configFromBackendStatus({ deploymentUrl: "http://127.0.0.1:6174/" })
    ).toEqual({
      deploymentUrl: "http://127.0.0.1:6174/",
      assistantId: DEFAULT_ASSISTANT_ID,
    });
  });

  it("rejects a missing or malformed backend address", () => {
    expect(configFromBackendStatus({})).toBeNull();
    expect(configFromBackendStatus({ deploymentUrl: "not a url" })).toBeNull();
  });
});
