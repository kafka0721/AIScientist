"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PROVIDERS = [
  ["anthropic", "Anthropic"],
  ["openai", "OpenAI"],
  ["google-genai", "Google Gemini"],
  ["openrouter", "OpenRouter"],
  ["deepseek", "DeepSeek"],
  ["dashscope", "Alibaba DashScope"],
  ["dashscope-code", "DashScope Coding Plan"],
  ["moonshot", "Moonshot"],
  ["kimi-coding", "Kimi Coding Plan"],
  ["minimax", "MiniMax"],
  ["nvidia", "NVIDIA NIM"],
  ["siliconflow", "SiliconFlow"],
  ["zhipu", "Zhipu AI"],
  ["zhipu-code", "Zhipu Coding Plan"],
  ["volcengine", "Volcengine Ark"],
  ["custom-openai", "Custom OpenAI-compatible"],
  ["custom-anthropic", "Custom Anthropic-compatible"],
  ["ollama", "Ollama (local)"],
] as const;

interface ModelEntry {
  name: string;
  modelId: string;
  provider: string;
}

interface RuntimeConfig {
  provider: string;
  model: string;
  keyConfigured: boolean;
  apiKeyHint: string | null;
  baseUrl: string;
  baseUrlSupported: boolean;
  models: ModelEntry[];
}

interface ApiConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: () => void;
}

export function ApiConfigDialog({
  open,
  onOpenChange,
  onUpdated,
}: ApiConfigDialogProps) {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setApiKey("");
    void fetch("/api/runtime-config", { cache: "no-store" })
      .then(async (response) => {
        const body = (await response.json().catch(() => null)) as
          | RuntimeConfig
          | {
              error?: string;
            }
          | null;
        if (!response.ok || !body || !("provider" in body)) {
          throw new Error(
            (body && "error" in body && body.error) ||
              "Could not load API configuration."
          );
        }
        return body as RuntimeConfig;
      })
      .then((next) => {
        if (cancelled) return;
        setConfig(next);
        setProvider(next.provider);
        setModel(next.model);
        setCustomModel(
          next.models.some(
            (entry) =>
              entry.provider === next.provider && entry.name === next.model
          )
            ? ""
            : next.model
        );
        setBaseUrl(next.baseUrl);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load API configuration."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const selectedProvider = PROVIDERS.find(([value]) => value === provider);
  const supportsBaseUrl =
    selectedProvider?.[0] === config?.provider
      ? Boolean(config?.baseUrlSupported)
      : [
          "anthropic",
          "openai",
          "minimax",
          "custom-openai",
          "custom-anthropic",
          "ollama",
        ].includes(provider);
  const usesApiKey = provider !== "ollama";
  const knownModels = Array.from(
    new Map(
      (config?.models ?? [])
        .filter((entry) => entry.provider === provider)
        .map((entry) => [entry.name, entry])
    ).values()
  );

  const selectProvider = (nextProvider: string) => {
    setProvider(nextProvider);
    setCustomModel("");
    const firstModel = config?.models.find(
      (entry) => entry.provider === nextProvider
    );
    setModel(firstModel?.name ?? "");
  };

  const save = async () => {
    const modelToSave = customModel.trim() || model;
    if (!modelToSave) {
      setError("Enter a model name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, string> = {
        provider,
        model: modelToSave,
      };
      if (apiKey.trim()) payload.apiKey = apiKey.trim();
      if (supportsBaseUrl) payload.baseUrl = baseUrl.trim();
      const response = await fetch("/api/runtime-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await response.json().catch(() => null)) as
        | RuntimeConfig
        | {
            error?: string;
          }
        | null;
      if (!response.ok || !body || !("provider" in body)) {
        throw new Error(
          (body && "error" in body && body.error) ||
            "Could not update API configuration."
        );
      }
      setConfig(body as RuntimeConfig);
      setApiKey("");
      onUpdated();
      toast.success(
        "API configuration updated. New requests use it immediately."
      );
      onOpenChange(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Could not update API configuration."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>API configuration</DialogTitle>
          <DialogDescription>
            Changes are saved locally and applied to new requests immediately.
            Existing running requests continue with their current connection.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="api-provider">Provider</Label>
            <Select
              value={provider}
              onValueChange={selectProvider}
              disabled={loading || saving}
            >
              <SelectTrigger id="api-provider">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map(([value, label]) => (
                  <SelectItem
                    key={value}
                    value={value}
                  >
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-model">Supported model</Label>
            <Select
              value={
                knownModels.some((entry) => entry.name === model)
                  ? model
                  : undefined
              }
              onValueChange={(nextModel) => {
                setModel(nextModel);
                setCustomModel("");
              }}
              disabled={loading || saving || knownModels.length === 0}
            >
              <SelectTrigger id="api-model">
                <SelectValue placeholder="No supported models found" />
              </SelectTrigger>
              <SelectContent>
                {knownModels.map((entry) => (
                  <SelectItem
                    key={`${entry.provider}:${entry.name}`}
                    value={entry.name}
                  >
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {knownModels.length > 0
                ? `${knownModels.length} supported models found for this provider.`
                : "No catalog models are available for this provider."}
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-custom-model">Custom model</Label>
            <Input
              id="api-custom-model"
              value={customModel}
              onChange={(event) => setCustomModel(event.target.value)}
              disabled={loading || saving}
              placeholder="Optional: override the selected model"
              autoComplete="off"
            />
          </div>
          {usesApiKey && (
            <div className="grid gap-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                disabled={loading || saving}
                placeholder={
                  config?.keyConfigured
                    ? `Configured (${
                        config.apiKeyHint || "hidden"
                      }); leave blank to keep`
                    : "Enter API key"
                }
                autoComplete="new-password"
              />
              <p className="text-xs text-muted-foreground">
                Keys are write-only and are never shown in this panel.
              </p>
            </div>
          )}
          {supportsBaseUrl && (
            <div className="grid gap-2">
              <Label htmlFor="api-base-url">Base URL</Label>
              <Input
                id="api-base-url"
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                disabled={loading || saving}
                placeholder="https://api.example.com/v1"
                autoComplete="off"
              />
            </div>
          )}
          {error && (
            <p
              role="alert"
              className="text-sm text-destructive"
            >
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            onClick={save}
            disabled={loading || saving}
          >
            {saving ? "Saving..." : "Save API settings"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
