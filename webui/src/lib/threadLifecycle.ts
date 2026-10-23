export interface RunCancelClient {
  runs: {
    list(
      threadId: string,
      options?: { status?: string; limit?: number }
    ): Promise<Array<{ run_id: string }>>;
    cancel(threadId: string, runId: string, wait?: boolean): Promise<void>;
  };
}

const CANCELABLE_RUN_STATUSES = ["pending", "running"] as const;

export async function cancelActiveRuns(
  client: RunCancelClient,
  threadId: string
): Promise<void> {
  const lists = await Promise.allSettled(
    CANCELABLE_RUN_STATUSES.map((status) =>
      client.runs.list(threadId, { status, limit: 100 })
    )
  );
  const listFailure = lists.find((result) => result.status === "rejected");
  if (listFailure?.status === "rejected") throw listFailure.reason;
  const runIds = lists
    .flatMap((result) => (result.status === "fulfilled" ? result.value : []))
    .map((run) => run.run_id)
    .filter((runId, index, all) => runId && all.indexOf(runId) === index);
  const cancellations = await Promise.allSettled(
    runIds.map((runId) => client.runs.cancel(threadId, runId, true))
  );
  const failure = cancellations.find((result) => result.status === "rejected");
  if (failure?.status === "rejected") throw failure.reason;
}

export interface PendingTaskClient extends RunCancelClient {
  threads: {
    getState(threadId: string): Promise<{ next?: unknown[] }>;
    updateState(threadId: string, options: { values: null; asNode: string }): Promise<unknown>;
  };
}

export async function abandonPendingTask(client: PendingTaskClient, threadId: string): Promise<void> {
  await cancelActiveRuns(client, threadId);
  const state = await client.threads.getState(threadId);
  if (!Array.isArray(state.next) || state.next.length === 0) return;
  await client.threads.updateState(threadId, { values: null, asNode: "__end__" });
  const after = await client.threads.getState(threadId);
  if (!Array.isArray(after.next) || after.next.length > 0) {
    throw new Error("The pending task is still present after clearing the checkpoint.");
  }
}
