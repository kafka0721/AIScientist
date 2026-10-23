export interface DeploymentConfig {
  deploymentUrl: string;
  assistantId: string;
  langsmithApiKey?: string;
}

// The UI always talks to the AIScientist main agent. writing-agent and
// data-analysis-agent are internal sub-agents and are intentionally not
// user-selectable, so the assistant is fixed rather than configurable.
export const DEFAULT_ASSISTANT_ID = "AIScientist";

const CONFIG_KEY = "witaiscientist-config";

/**
 * Build the browser connection record from the launcher's safe local-status
 * endpoint. Provider credentials and model choices stay on the backend.
 */
export function configFromBackendStatus(value: unknown): DeploymentConfig | null {
  if (!value || typeof value !== "object") return null;
  const deploymentUrl = (value as { deploymentUrl?: unknown }).deploymentUrl;
  if (typeof deploymentUrl !== "string" || !deploymentUrl.trim()) return null;
  try {
    new URL(deploymentUrl.trim());
  } catch {
    return null;
  }
  return {
    deploymentUrl: deploymentUrl.trim(),
    assistantId: DEFAULT_ASSISTANT_ID,
  };
}

export function getConfig(): DeploymentConfig | null {
  if (typeof window === "undefined") return null;

  try {
    const stored = localStorage.getItem(CONFIG_KEY);
    if (!stored) return null;

    const parsed = JSON.parse(stored) as DeploymentConfig;
    // A stored config with no usable deployment URL would make the SDK send
    // requests to the app's own origin (404s). Treat it as unconfigured so
    // the config dialog reappears instead.
    if (!parsed.deploymentUrl?.trim()) return null;
    // Always pin the assistant to the AIScientist main agent.
    return { ...parsed, assistantId: DEFAULT_ASSISTANT_ID };
  } catch {
    return null;
  }
}

export function saveConfig(config: DeploymentConfig): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
  } catch {
    // Storage can be unavailable in private/restricted browser contexts.
  }
}
