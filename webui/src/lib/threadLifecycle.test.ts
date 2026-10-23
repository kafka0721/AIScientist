import { describe, expect, it, vi } from "vitest";
import { abandonPendingTask, cancelActiveRuns } from "@/lib/threadLifecycle";

function fakeClient(byStatus: Record<string, Array<{ run_id: string }>>) {
  return {
    runs: {
      list: vi.fn(
        async (_threadId: string, options?: { status?: string }) =>
          byStatus[options?.status ?? ""] ?? []
      ),
      cancel: vi.fn(async () => {}),
    },
  };
}

describe("cancelActiveRuns", () => {
  it("cancels every pending and running run", async () => {
    const client = fakeClient({
      pending: [{ run_id: "r1" }],
      running: [{ run_id: "r2" }, { run_id: "r3" }],
    });
    await cancelActiveRuns(client, "t1");
    expect(client.runs.cancel).toHaveBeenCalledTimes(3);
    expect(client.runs.cancel).toHaveBeenCalledWith("t1", "r2", true);
  });

  it("does nothing when there are no active runs", async () => {
    const client = fakeClient({});
    await cancelActiveRuns(client, "t1");
    expect(client.runs.cancel).not.toHaveBeenCalled();
  });

  it("reports cancel failures", async () => {
    const client = fakeClient({ running: [{ run_id: "r1" }] });
    client.runs.cancel.mockRejectedValueOnce(new Error("gone"));
    await expect(cancelActiveRuns(client, "t1")).rejects.toThrow("gone");
  });

  it("does not cancel the same run twice when its status changes during listing", async () => {
    const client = fakeClient({
      pending: [{ run_id: "r1" }],
      running: [{ run_id: "r1" }],
    });
    await cancelActiveRuns(client, "t1");
    expect(client.runs.cancel).toHaveBeenCalledTimes(1);
  });
});

describe("abandonPendingTask", () => {
  it("clears a paused checkpoint without resuming its tool call", async () => {
    const client = {
      ...fakeClient({}),
      threads: {
        getState: vi.fn()
          .mockResolvedValueOnce({ next: ["HumanInTheLoopMiddleware.after_model"] })
          .mockResolvedValueOnce({ next: [] }),
        updateState: vi.fn(async () => ({})),
      },
    };
    await abandonPendingTask(client, "t1");
    expect(client.threads.updateState).toHaveBeenCalledWith("t1", {
      values: null,
      asNode: "__end__",
    });
    expect(client.runs.cancel).not.toHaveBeenCalled();
  });

  it("does not update an already idle checkpoint", async () => {
    const client = {
      ...fakeClient({}),
      threads: {
        getState: vi.fn(async () => ({ next: [] })),
        updateState: vi.fn(async () => ({})),
      },
    };
    await abandonPendingTask(client, "t1");
    expect(client.threads.updateState).not.toHaveBeenCalled();
  });
});
