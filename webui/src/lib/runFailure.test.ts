import { describe, expect, it } from "vitest";
import { checkpointFailure } from "./runFailure";

describe("checkpointFailure", () => {
  it("restores a recoverable model error after reload", () => {
    expect(checkpointFailure({ tasks: [{ name: "model", error: "APIConnectionError('Connection error.')" }], next: ["model"] }))
      .toEqual({ message: "APIConnectionError('Connection error.')", canRetry: true });
  });
  it("does not offer replay for tools, mixed nodes or a completed run", () => {
    for (const next of [["tools"], ["model", "tools"], []]) {
      expect(checkpointFailure({ tasks: [{ name: "model", error: "APIConnectionError" }], next })?.canRetry).toBe(false);
    }
    expect(checkpointFailure({ tasks: [{ name: "tools", error: "APIConnectionError" }], next: ["model"] })?.canRetry).toBe(false);
  });
  it("keeps other errors visible without enabling a model retry", () => {
    expect(checkpointFailure({ tasks: [{ name: "model", error: "BadRequestError" }], next: ["model"] }))
      .toEqual({ message: "BadRequestError", canRetry: false });
    expect(checkpointFailure({ tasks: [{ name: "model" }], next: ["model"] })).toBeNull();
  });
});
