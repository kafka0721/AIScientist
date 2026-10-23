"use client";

import Image from "next/image";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Clock3,
  Folder,
  FolderOpen,
  Grid2X2,
  List,
  Loader2,
  Plus,
  Search,
  Settings,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { HealthIndicator } from "@/app/components/HealthIndicator";
import { ThemeToggle } from "@/app/components/ThemeToggle";
import { cn } from "@/lib/utils";

export interface ProjectItem {
  path: string;
  name: string;
  addedAt: string;
  lastOpenedAt: string;
}

interface ProjectsResponse {
  active: string | null;
  switchingSupported: boolean;
  projects: ProjectItem[];
}

interface FolderResponse {
  path: string;
  parent: string | null;
  entries: Array<{ name: string; path: string }>;
  error?: string;
}

function relativeTime(timestamp: string): string {
  const elapsed = Date.now() - new Date(timestamp).getTime();
  if (!Number.isFinite(elapsed) || elapsed < 60_000) return "just now";
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

async function responseError(response: Response, fallback: string) {
  const body = (await response.json().catch(() => null)) as {
    error?: string;
  } | null;
  return body?.error || fallback;
}

function FolderPicker({
  open,
  onOpenChange,
  initialPath,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialPath?: string | null;
  onSelect: (path: string) => Promise<void>;
}) {
  const [folder, setFolder] = useState<FolderResponse | null>(null);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const browse = useCallback(async (next?: string | null) => {
    setLoading(true);
    try {
      const query = next ? `?path=${encodeURIComponent(next)}` : "";
      const response = await fetch(`/api/projects/browse${query}`, {
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error(
          await responseError(response, "Could not open that folder.")
        );
      const data = (await response.json()) as FolderResponse;
      setFolder(data);
      setPath(data.path);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not open that folder."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void browse(initialPath);
  }, [browse, initialPath, open]);

  const openTypedPath = (event: FormEvent) => {
    event.preventDefault();
    void browse(path);
  };

  const select = async () => {
    if (!folder || submitting) return;
    setSubmitting(true);
    try {
      await onSelect(folder.path);
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="gap-0 overflow-hidden rounded-lg p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-border px-5 py-4">
          <DialogTitle className="font-serif text-lg font-normal">
            Add project folder
          </DialogTitle>
          <DialogDescription>
            Choose an existing folder. Imaging Scientist will use it as the agent
            workspace.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={openTypedPath}
          className="flex gap-2 border-b border-border p-3"
        >
          <Input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            aria-label="Folder path"
            className="h-9 rounded border-border bg-background font-mono text-xs"
          />
          <Button
            type="submit"
            variant="outline"
            className="h-9 rounded px-3"
            disabled={loading}
          >
            Open
          </Button>
        </form>
        <div className="h-[360px] overflow-y-auto bg-[var(--color-background)] p-2">
          {loading ? (
            <div className="flex h-full items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" /> Loading folders
            </div>
          ) : (
            <div className="space-y-1">
              {folder?.parent && (
                <button
                  type="button"
                  onClick={() => void browse(folder.parent)}
                  className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <ArrowLeft className="size-4" /> Parent folder
                </button>
              )}
              {folder?.entries.map((entry) => (
                <button
                  type="button"
                  key={entry.path}
                  onClick={() => void browse(entry.path)}
                  className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-accent"
                >
                  <Folder className="size-4 text-[var(--brand)]" />
                  <span className="truncate">{entry.name}</span>
                </button>
              ))}
              {folder && folder.entries.length === 0 && (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  No subfolders
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter className="flex-row items-center border-t border-border px-4 py-3 sm:justify-between">
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">
            {folder?.path}
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="rounded"
              onClick={select}
              disabled={!folder || submitting}
            >
              {submitting && <Loader2 className="size-4 animate-spin" />}
              Add folder
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectsHome({
  deploymentUrl,
  onReconnect,
  onOpenProject,
  onOpenSettings,
}: {
  deploymentUrl: string;
  onReconnect: (url: string) => void;
  onOpenProject: (path: string) => Promise<void>;
  onOpenSettings: () => void;
}) {
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/projects", { cache: "no-store" });
      if (!response.ok)
        throw new Error(
          await responseError(response, "Could not load projects.")
        );
      setData((await response.json()) as ProjectsResponse);
      setError(null);
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Could not load projects."
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const projects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return data?.projects ?? [];
    return (data?.projects ?? []).filter(
      (project) =>
        project.name.toLowerCase().includes(normalized) ||
        project.path.toLowerCase().includes(normalized)
    );
  }, [data?.projects, query]);

  const addFolder = async (path: string) => {
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "add", path }),
    });
    if (!response.ok) {
      const message = await responseError(response, "Could not add project.");
      toast.error(message);
      throw new Error(message);
    }
    await load();
  };

  const remove = async (project: ProjectItem) => {
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "remove", path: project.path }),
    });
    if (!response.ok) {
      toast.error(await responseError(response, "Could not remove project."));
      return;
    }
    await load();
  };

  const open = async (path: string) => {
    if (opening) return;
    setOpening(path);
    try {
      await onOpenProject(path);
    } catch (nextError) {
      toast.error(
        nextError instanceof Error
          ? nextError.message
          : "Could not open project."
      );
      setOpening(null);
    }
  };

  return (
    <div className="science-workbench flex h-dvh flex-col bg-[var(--color-background)] text-foreground">
      <FolderPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        initialPath={data?.active}
        onSelect={addFolder}
      />
      <header className="flex h-[58px] shrink-0 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur-xl sm:px-7">
        <div className="flex items-center gap-3">
          <Image
            src="/imaging-scientist-avatar.png"
            alt="Imaging Scientist"
            width={28}
            height={28}
            className="size-7 rounded-full object-cover"
            priority
          />
          <span className="font-serif text-[22px] leading-none">
            Imaging Scientist
          </span>
        </div>
        <div className="ml-auto hidden w-full max-w-[300px] items-center gap-2 rounded border border-border bg-background px-3 md:flex">
          <Search className="size-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search projects..."
            className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
        <Button
          className="h-9 rounded px-4"
          onClick={() => setPickerOpen(true)}
        >
          <Plus className="size-4" /> New project
        </Button>
        <ThemeToggle />
        <Button
          variant="outline"
          size="icon"
          className="size-9 rounded"
          onClick={onOpenSettings}
          title="Settings"
        >
          <Settings className="size-4" />
        </Button>
        <div className="hidden lg:block">
          <HealthIndicator
            deploymentUrl={deploymentUrl}
            onReconnect={onReconnect}
          />
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1240px] flex-1 overflow-y-auto px-5 py-10 sm:px-8 sm:py-16">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <h1 className="font-serif text-xl font-normal">Projects</h1>
          <span className="font-mono text-xs text-muted-foreground">
            {data?.projects.length ?? 0}
          </span>
          <div className="ml-auto flex rounded border border-border bg-muted/40 p-0.5">
            <button
              type="button"
              className={cn(
                "grid size-8 place-items-center rounded-sm",
                view === "grid"
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground"
              )}
              onClick={() => setView("grid")}
              title="Grid view"
            >
              <Grid2X2 className="size-4" />
            </button>
            <button
              type="button"
              className={cn(
                "grid size-8 place-items-center rounded-sm",
                view === "list"
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground"
              )}
              onClick={() => setView("list")}
              title="List view"
            >
              <List className="size-4" />
            </button>
          </div>
        </div>

        <div className="mb-5 flex items-center gap-2 rounded border border-border bg-background px-3 md:hidden">
          <Search className="size-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search projects..."
            className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </div>

        {error ? (
          <div className="border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">
            {error}
          </div>
        ) : !data ? (
          <div className="flex h-48 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" /> Loading projects
          </div>
        ) : (
          <div
            className={cn(
              view === "grid"
                ? "grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
                : "divide-y divide-border border border-border bg-background"
            )}
          >
            {projects.map((project) => {
              const active = project.path === data.active;
              const busy = opening === project.path;
              return (
                <div
                  key={project.path}
                  className={cn(
                    "group relative min-w-0 transition-colors hover:bg-accent/60",
                    view === "grid"
                      ? "min-h-[124px] border border-border bg-background"
                      : "bg-background"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => void open(project.path)}
                    className={cn(
                      "flex h-full w-full min-w-0 gap-4 p-4 text-left",
                      view === "grid"
                        ? "min-h-[124px] items-start p-5"
                        : "items-center pr-12"
                    )}
                  >
                    <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-serif text-base">
                          {project.name}
                        </span>
                        {active && (
                          <span className="rounded-sm border border-emerald-600/30 bg-emerald-600/5 px-1.5 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-400">
                            active
                          </span>
                        )}
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {project.path}
                      </div>
                      <div
                        className={cn(
                          "flex items-center gap-1.5 text-xs text-muted-foreground",
                          view === "grid" ? "mt-6" : "mt-1"
                        )}
                      >
                        {busy ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Clock3 className="size-3.5" />
                        )}
                        {busy
                          ? "Opening workspace..."
                          : relativeTime(project.lastOpenedAt)}
                      </div>
                    </div>
                  </button>
                  {!active && (
                    <button
                      type="button"
                      aria-label={`Remove ${project.name}`}
                      title="Remove from projects"
                      onClick={(event) => {
                        event.stopPropagation();
                        void remove(project);
                      }}
                      className="absolute right-3 top-3 grid size-7 place-items-center rounded text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive focus:opacity-100 group-hover:opacity-100"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </div>
              );
            })}
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              className={cn(
                "flex items-center justify-center gap-2 border border-dashed border-border text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-accent/40 hover:text-foreground",
                view === "grid" ? "min-h-[124px] flex-col" : "p-5"
              )}
            >
              <Plus className="size-4" />{" "}
              <span className="font-serif">new project</span>
            </button>
          </div>
        )}
        {data && !data.switchingSupported && (
          <p className="mt-5 text-xs text-muted-foreground">
            Workspace switching becomes available after launching Imaging Scientist
            with start-webui.bat or ImagingSci WebUI.
          </p>
        )}
      </main>
    </div>
  );
}
