export function checkpointFailure(state: {
  tasks?: Array<{ name?: string; error?: unknown }>;
  next?: unknown[];
}): { message: string; canRetry: boolean } | null {
  const failed = (state.tasks ?? []).filter((task) => task.error);
  if (!failed.length) return null;
  const message = failed.map((task) => String(task.error)).join("\n");
  return {
    message,
    // A null-input resume retries pending graph nodes. Offer it only for a
    // model connection failure, never an unknown or failed tool operation.
    canRetry:
      failed.every(
        (task) =>
          task.name === "model" &&
          /APIConnectionError|APITimeoutError/.test(String(task.error))
      ) &&
      Boolean(state.next?.length) &&
      state.next!.every((name) => name === "model"),
  };
}
