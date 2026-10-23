"use client";

import {
  Brain,
  FileText,
  FolderTree,
  MessageSquare,
  Puzzle,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface OpenWorkspaceDocument {
  path: string;
  size?: number;
}

interface WorkbenchTabsProps {
  activeView: string | null;
  files: OpenWorkspaceDocument[];
  dirtyFiles?: ReadonlySet<string>;
  onSelect: (view: string | null) => void;
  onCloseFile: (path: string) => void;
}

const FIXED_TABS: Array<{
  id: string | null;
  label: string;
  Icon: LucideIcon;
}> = [
  { id: null, label: "Chat", Icon: MessageSquare },
  { id: "files", label: "Files", Icon: FolderTree },
  { id: "skills", label: "Skills", Icon: Puzzle },
];

function fileView(path: string): string {
  return `file:${encodeURIComponent(path)}`;
}

function TabButton({
  active,
  label,
  Icon,
  dirty,
  onClick,
  onClose,
}: {
  active: boolean;
  label: string;
  Icon: LucideIcon;
  dirty?: boolean;
  onClick: () => void;
  onClose?: () => void;
}) {
  return (
    <div
      className={cn(
        "group relative flex h-9 shrink-0 items-center border-r border-border",
        active
          ? "bg-background text-foreground"
          : "bg-muted/35 text-muted-foreground"
      )}
    >
      <button
        type="button"
        onClick={onClick}
        className="flex h-full min-w-0 items-center gap-1.5 px-3 text-xs transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        title={label}
      >
        <Icon
          className="size-3.5 shrink-0"
          aria-hidden="true"
        />
        <span className="max-w-36 truncate">{label}</span>
        {dirty && (
          <span
            className="size-1.5 shrink-0 rounded-full bg-[var(--brand-solid)]"
            aria-label="Unsaved changes"
          />
        )}
      </button>
      {onClose && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onClose();
          }}
          className="mr-1 flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-70 transition-colors hover:bg-muted hover:text-foreground group-hover:opacity-100"
          aria-label={`Close ${label}`}
          title="Close"
        >
          <X
            className="size-3.5"
            aria-hidden="true"
          />
        </button>
      )}
      {active && (
        <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[var(--brand-solid)]" />
      )}
    </div>
  );
}

export function WorkbenchTabs({
  activeView,
  files,
  dirtyFiles,
  onSelect,
  onCloseFile,
}: WorkbenchTabsProps) {
  const contextual =
    activeView === "memory"
      ? { id: "memory", label: "Memory", Icon: Brain }
      : null;

  return (
    <nav
      aria-label="Workbench tabs"
      className="flex h-9 shrink-0 overflow-x-auto border-b border-border bg-muted/30 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {FIXED_TABS.map(({ id, label, Icon }) => (
        <TabButton
          key={id ?? "chat"}
          active={activeView === id}
          label={label}
          Icon={Icon}
          onClick={() => onSelect(id)}
        />
      ))}
      {contextual && (
        <TabButton
          active
          label={contextual.label}
          Icon={contextual.Icon}
          onClick={() => onSelect(contextual.id)}
        />
      )}
      {files.map((file) => {
        const id = fileView(file.path);
        return (
          <TabButton
            key={file.path}
            active={activeView === id}
            label={file.path.split("/").pop() || file.path}
            Icon={FileText}
            dirty={dirtyFiles?.has(file.path)}
            onClick={() => onSelect(id)}
            onClose={() => onCloseFile(file.path)}
          />
        );
      })}
    </nav>
  );
}

// This small URL-view helper intentionally lives beside the tab contract.
// eslint-disable-next-line react-refresh/only-export-components
export function workspaceFileView(path: string): string {
  return fileView(path);
}
