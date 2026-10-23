"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Brain,
  FileText,
  FolderTree,
  History,
  MessageSquarePlus,
  PanelLeft,
  PanelRight,
  Search,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

type CommandCategory = "Actions" | "Views" | "Projects" | "Sessions" | "Files";

interface CommandItem {
  id: string;
  label: string;
  detail?: string;
  category: CommandCategory;
  Icon: LucideIcon;
  run: () => void | Promise<void>;
}

interface WorkbenchCommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceDir: string;
  assistantId: string;
  onNewChat: () => void;
  onShowProjects: () => void;
  onOpenView: (view: string | null) => void;
  onOpenFile: (file: { path: string; size?: number }) => void;
  onOpenThread: (threadId: string) => void | Promise<void>;
  onToggleSidebar: () => void;
  onToggleInspector: () => void;
  onOpenSettings: () => void;
  onOpenProject: (path: string) => void | Promise<void>;
}

interface WorkspaceResponse {
  entries?: Array<{
    path: string;
    name: string;
    size?: number;
    type: "file" | "dir";
  }>;
}

interface ProjectsResponse {
  projects?: Array<{ path: string; name: string }>;
}

function threadLabel(metadata: Record<string, unknown>, fallback: string) {
  for (const key of ["title", "auto_title", "preview"] as const) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return fallback;
}

export function WorkbenchCommandPalette({
  open,
  onOpenChange,
  workspaceDir,
  assistantId,
  onNewChat,
  onShowProjects,
  onOpenView,
  onOpenFile,
  onOpenThread,
  onToggleSidebar,
  onToggleInspector,
  onOpenSettings,
  onOpenProject,
}: WorkbenchCommandPaletteProps) {
  const client = useClient();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const [remoteItems, setRemoteItems] = useState<CommandItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const staticItems = useMemo<CommandItem[]>(
    () => [
      {
        id: "new-chat",
        label: "New chat",
        detail: "Start a fresh research session",
        category: "Actions",
        Icon: MessageSquarePlus,
        run: onNewChat,
      },
      {
        id: "projects",
        label: "Show all projects",
        detail: "Return to the project switcher",
        category: "Actions",
        Icon: FolderTree,
        run: onShowProjects,
      },
      {
        id: "sidebar",
        label: "Toggle research sidebar",
        category: "Actions",
        Icon: PanelLeft,
        run: onToggleSidebar,
      },
      {
        id: "inspector",
        label: "Toggle workspace inspector",
        category: "Actions",
        Icon: PanelRight,
        run: onToggleInspector,
      },
      {
        id: "settings",
        label: "Open settings",
        category: "Actions",
        Icon: Settings,
        run: onOpenSettings,
      },
      {
        id: "view-chat",
        label: "Chat",
        category: "Views",
        Icon: MessageSquarePlus,
        run: () => onOpenView(null),
      },
      {
        id: "view-files",
        label: "Files",
        category: "Views",
        Icon: FolderTree,
        run: () => onOpenView("files"),
      },
      {
        id: "view-skills",
        label: "Skills",
        category: "Views",
        Icon: Sparkles,
        run: () => onOpenView("skills"),
      },
      {
        id: "view-memory",
        label: "Memory",
        category: "Views",
        Icon: Brain,
        run: () => onOpenView("memory"),
      },
    ],
    [
      onNewChat,
      onOpenSettings,
      onOpenView,
      onShowProjects,
      onToggleInspector,
      onToggleSidebar,
    ]
  );

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelected(0);
    requestAnimationFrame(() => inputRef.current?.focus());

    let cancelled = false;
    const load = async () => {
      const isUuid = /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(assistantId);
      const metadata = {
        ...(isUuid ? { assistant_id: assistantId } : { graph_id: assistantId }),
        workspace_dir: workspaceDir,
      };
      const [projectsResult, filesResult, threadsResult] =
        await Promise.allSettled([
          fetch("/api/projects", { cache: "no-store" }).then((response) =>
            response.ok
              ? (response.json() as Promise<ProjectsResponse>)
              : { projects: [] }
          ),
          fetch("/api/workspace?recursive=1", { cache: "no-store" }).then(
            (response) =>
              response.ok
                ? (response.json() as Promise<WorkspaceResponse>)
                : { entries: [] }
          ),
          client.threads.search({
            metadata,
            limit: 50,
            sortBy: "updated_at",
            sortOrder: "desc",
          }),
        ]);
      if (cancelled) return;

      const items: CommandItem[] = [];
      if (projectsResult.status === "fulfilled") {
        for (const project of projectsResult.value.projects ?? []) {
          items.push({
            id: `project:${project.path}`,
            label: project.name,
            detail: project.path,
            category: "Projects",
            Icon: FolderTree,
            run: () => onOpenProject(project.path),
          });
        }
      }
      if (threadsResult.status === "fulfilled") {
        for (const thread of threadsResult.value) {
          const metadata = (thread.metadata ?? {}) as Record<string, unknown>;
          items.push({
            id: `thread:${thread.thread_id}`,
            label: threadLabel(metadata, thread.thread_id),
            detail: thread.thread_id,
            category: "Sessions",
            Icon: History,
            run: () => onOpenThread(thread.thread_id),
          });
        }
      }
      if (filesResult.status === "fulfilled") {
        for (const file of filesResult.value.entries ?? []) {
          if (file.type !== "file") continue;
          items.push({
            id: `file:${file.path}`,
            label: file.name,
            detail: file.path,
            category: "Files",
            Icon: FileText,
            run: () => onOpenFile({ path: file.path, size: file.size }),
          });
        }
      }
      setRemoteItems(items);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [
    assistantId,
    client,
    onOpenFile,
    onOpenProject,
    onOpenThread,
    open,
    workspaceDir,
  ]);

  const items = useMemo(() => {
    const terms = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    return [...staticItems, ...remoteItems]
      .filter((item) => {
        const text = `${item.label} ${item.detail ?? ""} ${
          item.category
        }`.toLocaleLowerCase();
        return terms.every((term) => text.includes(term));
      })
      .slice(0, 60);
  }, [query, remoteItems, staticItems]);

  useEffect(() => setSelected(0), [query]);

  const run = (item: CommandItem | undefined) => {
    if (!item) return;
    onOpenChange(false);
    void item.run();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent
        showCloseButton={false}
        className="top-[18vh] block max-h-[min(68vh,620px)] translate-y-0 gap-0 overflow-hidden rounded-md p-0 sm:max-w-2xl"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setSelected((value) =>
              items.length ? Math.min(value + 1, items.length - 1) : 0
            );
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setSelected((value) => Math.max(value - 1, 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            run(items[selected]);
          }
        }}
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <div className="flex h-12 items-center gap-3 border-b border-border px-4">
          <Search
            className="size-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search commands, sessions, projects, and files..."
            aria-label="Search commands"
            className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:block">
            ESC
          </kbd>
        </div>
        <div
          role="listbox"
          aria-label="Commands"
          className="max-h-[calc(min(68vh,620px)-3rem)] overflow-y-auto p-1.5"
        >
          {items.length ? (
            items.map((item, index) => (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={index === selected}
                onMouseEnter={() => setSelected(index)}
                onClick={() => run(item)}
                className={cn(
                  "flex w-full items-center gap-3 rounded px-3 py-2 text-left",
                  index === selected
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground"
                )}
              >
                <item.Icon
                  className="size-4 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{item.label}</div>
                  {item.detail && (
                    <div className="truncate text-[11px] text-muted-foreground">
                      {item.detail}
                    </div>
                  )}
                </div>
                <span className="shrink-0 text-[10px] uppercase text-muted-foreground">
                  {item.category}
                </span>
              </button>
            ))
          ) : (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              No matching commands
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
