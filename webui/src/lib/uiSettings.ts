"use client";

import { useCallback, useEffect, useState } from "react";

const COLLAPSE_AGENT_ACTIONS_KEY = "witaisci.ui.collapseAgentActions";

function readCollapseAgentActions(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(COLLAPSE_AGENT_ACTIONS_KEY);
    if (raw === null) return true; // default: collapse
    return raw === "true";
  } catch {
    return true;
  }
}

/**
 * Whether completed agent-action groups should auto-collapse once a turn
 * settles. Defaults to true. Stored in localStorage so the preference
 * persists across reloads. Standalone from `DeploymentConfig` because this
 * is a UI preference, not a server connection.
 */
export function useCollapseAgentActions(): {
  value: boolean;
  setValue: (next: boolean) => void;
} {
  const [value, setValueState] = useState<boolean>(readCollapseAgentActions);

  // Pick up changes from other tabs / late init (e.g. SSR → CSR transition).
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== COLLAPSE_AGENT_ACTIONS_KEY) return;
      setValueState(readCollapseAgentActions());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setValue = useCallback((next: boolean) => {
    setValueState(next);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(COLLAPSE_AGENT_ACTIONS_KEY, String(next));
      } catch {
        // Keep the in-memory preference when persistence is unavailable.
      }
    }
  }, []);

  return { value, setValue };
}
