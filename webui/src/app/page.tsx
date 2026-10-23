"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import Image from "next/image";
import { useQueryState } from "nuqs";
import {
  configFromBackendStatus,
  getConfig,
  saveConfig,
  DeploymentConfig,
} from "@/lib/config";
import { ConfigDialog } from "@/app/components/ConfigDialog";
import { ApiConfigDialog } from "@/app/components/ApiConfigDialog";
import { Button } from "@/components/ui/button";
import { Assistant } from "@langchain/langgraph-sdk";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import {
  Settings,
  SquarePen,
  ChevronLeft,
  Folder,
  KeyRound,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  PanelRight,
  PanelRightClose,
  Search,
} from "lucide-react";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ThreadList } from "@/app/components/ThreadList";
import { ChatProvider } from "@/providers/ChatProvider";
import { ChatInterface } from "@/app/components/ChatInterface";
import { SkillsMarketplace } from "@/app/components/SkillsMarketplace";
import { MemoryPanel } from "@/app/components/MemoryPanel";
import { ThemeToggle } from "@/app/components/ThemeToggle";
import { HealthIndicator } from "@/app/components/HealthIndicator";
import { InspectorPanel } from "@/app/components/InspectorPanel";
import { ProjectsHome } from "@/app/components/ProjectsHome";
import { WorkspacePanel } from "@/app/components/WorkspacePanel";
import { WorkspaceDocument } from "@/app/components/WorkspaceDocument";
import {
  WorkbenchTabs,
  workspaceFileView,
  type OpenWorkspaceDocument,
} from "@/app/components/WorkbenchTabs";
import { WorkbenchCommandPalette } from "@/app/components/WorkbenchCommandPalette";
import { setThreadAutoApprove } from "@/lib/autoApprove";
import type { MainChatReporter } from "@/lib/asyncAgents";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface HomePageInnerProps {
  config: DeploymentConfig;
  configDialogOpen: boolean;
  setConfigDialogOpen: (open: boolean) => void;
  handleSaveConfig: (config: DeploymentConfig) => void;
}

function HomePageInner({
  config,
  configDialogOpen,
  setConfigDialogOpen,
  handleSaveConfig,
}: HomePageInnerProps) {
  const client = useClient();
  const [threadId, setThreadId] = useQueryState("threadId");
  const [projectPath, setProjectPath] = useQueryState("project");
  const [sidebar, setSidebar] = useQueryState("sidebar");
  const [view, setView] = useQueryState("view");
  const [memoryTab, setMemoryTab] = useQueryState("memoryTab");
  const [memoryObs, setMemoryObs] = useQueryState("memoryObs");
  const [memoryExec, setMemoryExec] = useQueryState("memoryExec");
  const [inspector, setInspector] = useQueryState("inspector");
  const [inspectorTab, setInspectorTab] = useQueryState("inspectorTab");

  const [mutateThreads, setMutateThreads] = useState<(() => void) | null>(null);
  const [interruptCount, setInterruptCount] = useState(0);
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [readyProject, setReadyProject] = useState<string | null>(null);
  const [backendRevision, setBackendRevision] = useState(0);
  const [isDesktopLayout, setIsDesktopLayout] = useState<boolean | null>(null);
  const [chatSessionRevision, setChatSessionRevision] = useState(0);
  const [apiConfigDialogOpen, setApiConfigDialogOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [openWorkspaceFiles, setOpenWorkspaceFiles] = useState<
    OpenWorkspaceDocument[]
  >([]);
  const [dirtyWorkspaceFiles, setDirtyWorkspaceFiles] = useState<Set<string>>(
    new Set()
  );
  const [filesLoadedForProject, setFilesLoadedForProject] = useState<
    string | null
  >(null);
  // "Submit a message on the main thread" — registered by ChatInterface (only
  // while it's mounted, i.e. on the chat view), used by the Agents board to loop
  // an async result back to the main agent. Null when not on the chat view.
  const [notifyMainChat, setNotifyMainChat] = useState<MainChatReporter | null>(
    null
  );

  useEffect(() => {
    if (view === "schedule") setView(null);
  }, [setView, view]);

  const fetchAssistant = useCallback(async () => {
    const isUUID =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        config.assistantId
      );

    const resolve = async (): Promise<Assistant> => {
      // A UUID addresses one assistant directly; otherwise list the graph's
      // assistants and prefer the system default (fall back to the first).
      if (isUUID) {
        return await client.assistants.get(config.assistantId);
      }
      const assistants = await client.assistants.search({
        graphId: config.assistantId,
        limit: 100,
      });
      const found =
        assistants.find((a) => a.metadata?.["created_by"] === "system") ??
        assistants[0];
      if (!found) throw new Error("No assistant found for this graph.");
      return found;
    };

    // The langgraph backend may not be ready the instant the page mounts — the
    // request then fails with "Failed to fetch". Retry a few times so a transient
    // startup race self-heals instead of surfacing a scary console error.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        setAssistant(await resolve());
        return;
      } catch (error) {
        if (attempt < 2) {
          await new Promise((r) => setTimeout(r, 700));
          continue;
        }
        console.warn(
          "Couldn't resolve the AIScientist assistant; addressing the graph by id instead. Is the backend running?",
          error
        );
      }
    }

    // Fallback: address the graph directly by id (works on `langgraph dev`).
    setAssistant({
      assistant_id: config.assistantId,
      graph_id: config.assistantId,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      config: {},
      metadata: {},
      version: 1,
      name: config.assistantId,
      context: {},
    });
  }, [client, config.assistantId]);

  useEffect(() => {
    if (!readyProject) {
      setAssistant(null);
      return;
    }
    fetchAssistant();
  }, [backendRevision, fetchAssistant, readyProject]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 768px)");
    const updateLayout = () => setIsDesktopLayout(mediaQuery.matches);

    updateLayout();
    mediaQuery.addEventListener("change", updateLayout);
    return () => mediaQuery.removeEventListener("change", updateLayout);
  }, []);

  useEffect(() => {
    if (isDesktopLayout === false && sidebar && inspector) {
      setInspector(null);
    }
  }, [inspector, isDesktopLayout, setInspector, sidebar]);

  useEffect(() => {
    if (!readyProject) return;
    const storageKey = `witaiscientist:open-files:${readyProject}`;
    try {
      const parsed = JSON.parse(
        localStorage.getItem(storageKey) || "[]"
      ) as unknown;
      const files = Array.isArray(parsed)
        ? parsed
            .filter((item): item is string => typeof item === "string")
            .map((path) => ({ path }))
        : [];
      setOpenWorkspaceFiles(files);
    } catch {
      setOpenWorkspaceFiles([]);
    }
    setDirtyWorkspaceFiles(new Set());
    setFilesLoadedForProject(readyProject);
  }, [readyProject]);

  useEffect(() => {
    if (!readyProject || filesLoadedForProject !== readyProject) return;
    localStorage.setItem(
      `witaiscientist:open-files:${readyProject}`,
      JSON.stringify(openWorkspaceFiles.map((file) => file.path))
    );
  }, [filesLoadedForProject, openWorkspaceFiles, readyProject]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const closeSidebar = useCallback(() => setSidebar(null), [setSidebar]);
  const closeInspector = useCallback(() => {
    setInspector(null);
    setInspectorTab(null);
  }, [setInspector, setInspectorTab]);
  const activateProject = useCallback(
    async (path: string) => {
      const response = await fetch("/api/projects/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const body = (await response.json().catch(() => null)) as {
        active?: string;
        error?: string;
      } | null;
      if (!response.ok || !body?.active) {
        throw new Error(body?.error || "Could not open this project.");
      }

      setAssistant(null);
      setReadyProject(body.active);
      setBackendRevision((revision) => revision + 1);
      setThreadAutoApprove(null, false);
      setThreadId(null);
      setView(null);
      setMemoryTab(null);
      setMemoryObs(null);
      setMemoryExec(null);
      setInspector(null);
      setInspectorTab(null);
      setSidebar("1");
      setChatSessionRevision((revision) => revision + 1);
      await setProjectPath(body.active);
    },
    [
      setInspector,
      setInspectorTab,
      setMemoryExec,
      setMemoryObs,
      setMemoryTab,
      setProjectPath,
      setSidebar,
      setThreadId,
      setView,
    ]
  );

  useEffect(() => {
    if (!projectPath || readyProject === projectPath) return;
    let cancelled = false;
    void activateProject(projectPath).catch((error) => {
      if (cancelled) return;
      toast.error(
        error instanceof Error ? error.message : "Could not open this project."
      );
      setReadyProject(null);
      void setProjectPath(null);
    });
    return () => {
      cancelled = true;
    };
  }, [activateProject, projectPath, readyProject, setProjectPath]);

  const showProjects = useCallback(() => {
    if (dirtyWorkspaceFiles.size > 0) {
      toast.info(
        "Save or cancel your file changes before leaving this project."
      );
      return;
    }
    setThreadAutoApprove(null, false);
    setThreadId(null);
    setView(null);
    setReadyProject(null);
    setAssistant(null);
    setProjectPath(null);
  }, [dirtyWorkspaceFiles, setProjectPath, setThreadId, setView]);
  const toggleSidebar = useCallback(() => {
    if (sidebar) {
      setSidebar(null);
      return;
    }
    if (isDesktopLayout === false) closeInspector();
    setSidebar("1");
  }, [closeInspector, isDesktopLayout, setSidebar, sidebar]);
  const toggleInspector = useCallback(() => {
    if (inspector) {
      closeInspector();
      return;
    }
    if (isDesktopLayout === false) setSidebar(null);
    setInspectorTab(null);
    setInspector("1");
  }, [
    closeInspector,
    inspector,
    isDesktopLayout,
    setInspector,
    setInspectorTab,
    setSidebar,
  ]);
  // Open the inspector straight on its Agents tab (composer pulse → board).
  const showAgentsInspector = useCallback(() => {
    setInspectorTab("agents");
    if (isDesktopLayout === false) setSidebar(null);
    setInspector("1");
  }, [isDesktopLayout, setInspector, setSidebar, setInspectorTab]);
  const sidebarToggleLabel = view
    ? sidebar
      ? "Hide navigation"
      : "Show navigation"
    : sidebar
    ? "Hide research"
    : "Show research";
  const startNewChat = useCallback(() => {
    setThreadAutoApprove(null, false);
    setThreadId(null);
    setView(null);
    setChatSessionRevision((revision) => revision + 1);
  }, [setThreadId, setView]);
  const openWorkspaceFile = useCallback(
    (file: OpenWorkspaceDocument) => {
      setOpenWorkspaceFiles((current) => {
        const existing = current.find((item) => item.path === file.path);
        if (existing) {
          if (existing.size == null && file.size != null) {
            return current.map((item) =>
              item.path === file.path ? { ...item, size: file.size } : item
            );
          }
          return current;
        }
        return [...current, file];
      });
      setView(workspaceFileView(file.path));
    },
    [setView]
  );
  const closeWorkspaceFile = useCallback(
    (path: string) => {
      if (dirtyWorkspaceFiles.has(path)) {
        toast.info("Save or cancel your changes before closing this tab.");
        return;
      }
      setOpenWorkspaceFiles((current) =>
        current.filter((file) => file.path !== path)
      );
      if (view === workspaceFileView(path)) setView(null);
    },
    [dirtyWorkspaceFiles, setView, view]
  );
  const setWorkspaceFileDirty = useCallback((path: string, dirty: boolean) => {
    setDirtyWorkspaceFiles((current) => {
      if (current.has(path) === dirty) return current;
      const next = new Set(current);
      if (dirty) next.add(path);
      else next.delete(path);
      return next;
    });
  }, []);
  const handleDashboardNav = useCallback(
    (
      target:
        | {
            view: "memory";
            tab: "identity" | "knowledge" | "history";
            obsId?: string;
            execId?: string;
          }
        | { view: "workspace" }
    ) => {
      if (target.view === "memory") {
        setMemoryTab(target.tab);
        setMemoryObs(target.obsId ?? null);
        setMemoryExec(target.execId ?? null);
        setView("memory");
      } else {
        if (inspector && inspectorTab !== "agents") {
          closeInspector();
          return;
        }
        if (isDesktopLayout === false) setSidebar(null);
        setInspectorTab(null);
        setInspector("1");
      }
    },
    [
      closeInspector,
      inspector,
      inspectorTab,
      isDesktopLayout,
      setInspector,
      setInspectorTab,
      setMemoryExec,
      setMemoryObs,
      setMemoryTab,
      setSidebar,
      setView,
    ]
  );
  const selectThread = useCallback(
    async (id: string) => {
      setThreadAutoApprove(null, false);
      setView(null);
      const sameThread = threadId === id;
      // Bump revision before the awaited URL update: the remount tears down
      // the stale `useChat` instance before `threadId` flips, so its persist
      // effect can't write the previous thread's labels onto the target
      // thread. Only bump when the thread actually changes — clicking the
      // active row (e.g. returning from the Memory view) must not tear down
      // ChatInterface and re-fetch the full `/history`.
      if (!sameThread) {
        setChatSessionRevision((revision) => revision + 1);
      }
      await setThreadId(id);
    },
    [setThreadId, setView, threadId]
  );

  if (!projectPath) {
    return (
      <>
        <ConfigDialog
          open={configDialogOpen}
          onOpenChange={setConfigDialogOpen}
          onSave={handleSaveConfig}
          initialConfig={config}
        />
        <ProjectsHome
          deploymentUrl={config.deploymentUrl}
          onReconnect={(url) =>
            handleSaveConfig({ ...config, deploymentUrl: url })
          }
          onOpenProject={activateProject}
          onOpenSettings={() => setConfigDialogOpen(true)}
        />
      </>
    );
  }

  if (readyProject !== projectPath) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center bg-[var(--color-background)] text-foreground">
        <Image
          src="/imaging-scientist-avatar.png"
          alt="Imaging Scientist"
          width={36}
          height={36}
          className="mb-5 size-9 rounded-full object-cover"
          priority
        />
        <Loader2 className="mb-3 size-5 animate-spin text-[var(--brand)]" />
        <p className="font-serif text-lg">Opening project workspace</p>
        <p className="mt-1 max-w-[min(90vw,620px)] truncate font-mono text-xs text-muted-foreground">
          {projectPath}
        </p>
      </div>
    );
  }

  return (
    <>
      <ConfigDialog
        open={configDialogOpen}
        onOpenChange={setConfigDialogOpen}
        onSave={handleSaveConfig}
        initialConfig={config}
      />
      <ApiConfigDialog
        open={apiConfigDialogOpen}
        onOpenChange={setApiConfigDialogOpen}
        onUpdated={() => setBackendRevision((revision) => revision + 1)}
      />
      <WorkbenchCommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
        workspaceDir={readyProject}
        assistantId={config.assistantId}
        onNewChat={startNewChat}
        onShowProjects={showProjects}
        onOpenView={setView}
        onOpenFile={openWorkspaceFile}
        onOpenThread={selectThread}
        onToggleSidebar={toggleSidebar}
        onToggleInspector={toggleInspector}
        onOpenSettings={() => setConfigDialogOpen(true)}
        onOpenProject={(path) => {
          if (dirtyWorkspaceFiles.size > 0) {
            toast.info(
              "Save or cancel your file changes before switching projects."
            );
            return;
          }
          void activateProject(path).catch((error) =>
            toast.error(
              error instanceof Error
                ? error.message
                : "Could not open this project."
            )
          );
        }}
      />
      <div className="science-workbench flex h-screen flex-col">
        <header className="flex h-14 items-center justify-between gap-2 border-b border-border bg-background/90 px-2.5 backdrop-blur-xl sm:px-4">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={showProjects}
              className="h-8 shrink-0 gap-1 rounded px-2 font-serif font-normal text-muted-foreground"
              title="Back to projects"
            >
              <ChevronLeft className="size-4" />
              <span className="hidden sm:inline">Projects</span>
            </Button>
            <span className="h-5 w-px bg-border" />
            <div className="flex min-w-0 items-center gap-2 border-r border-border pr-3">
              <Image
                src="/imaging-scientist-avatar.png"
                alt="Imaging Scientist"
                width={28}
                height={28}
                className="size-7 shrink-0 rounded-full object-cover"
                priority
              />
              <span className="hidden font-serif text-lg sm:inline">
                Imaging Scientist
              </span>
            </div>
            <div className="hidden min-w-0 items-center gap-2 md:flex">
              <Folder className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <div className="truncate font-serif text-sm leading-tight">
                  {readyProject.split(/[\\/]/).filter(Boolean).at(-1) ||
                    readyProject}
                </div>
                <div className="max-w-[260px] truncate font-mono text-[10px] leading-tight text-muted-foreground xl:max-w-[420px]">
                  {readyProject}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleSidebar}
                aria-label={sidebarToggleLabel}
                className="relative size-8"
              >
                {sidebar ? (
                  <PanelLeftClose
                    className="size-5"
                    aria-hidden="true"
                  />
                ) : (
                  <PanelLeft
                    className="size-5"
                    aria-hidden="true"
                  />
                )}
                {interruptCount > 0 && (
                  <span className="absolute right-0 top-0 inline-flex min-h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] text-destructive-foreground">
                    {interruptCount}
                  </span>
                )}
              </Button>
              {!sidebar && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={startNewChat}
                  aria-label="New chat"
                  className="size-8"
                >
                  <SquarePen
                    className="size-5"
                    aria-hidden="true"
                  />
                </Button>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCommandPaletteOpen(true)}
              aria-label="Open command palette"
              title="Search commands (Ctrl+K)"
              className="size-8"
            >
              <Search
                className="size-4"
                aria-hidden="true"
              />
            </Button>
            <HealthIndicator
              deploymentUrl={config.deploymentUrl}
              onReconnect={(url) =>
                handleSaveConfig({ ...config, deploymentUrl: url })
              }
            />
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setApiConfigDialogOpen(true)}
              aria-label="API configuration"
              title="API configuration"
              className="size-8"
            >
              <KeyRound
                className="size-4"
                aria-hidden="true"
              />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleInspector}
              aria-label={inspector ? "Hide inspector" : "Show workspace"}
              title={inspector ? "Hide inspector" : "Show workspace"}
              className="size-8"
            >
              {inspector ? (
                <PanelRightClose
                  className="size-5"
                  aria-hidden="true"
                />
              ) : (
                <PanelRight
                  className="size-5"
                  aria-hidden="true"
                />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setConfigDialogOpen(true)}
              aria-label="Settings"
              title="Settings"
              className="size-8"
            >
              <Settings
                className="size-5"
                aria-hidden="true"
              />
            </Button>
          </div>
        </header>

        <div className="relative flex-1 overflow-hidden">
          {sidebar && isDesktopLayout === false && (
            <div className="absolute inset-0 z-40 flex md:hidden">
              <button
                type="button"
                aria-label="Close research"
                className="absolute inset-0 bg-black/40"
                onClick={closeSidebar}
              />
              <aside
                aria-label={view ? "Navigation" : "Research navigation"}
                className="relative z-10 h-full w-[min(19rem,calc(100vw-2.25rem))] bg-background shadow-xl"
              >
                <ThreadList
                  workspaceDir={readyProject}
                  onClose={closeSidebar}
                  onNewChat={startNewChat}
                  onThreadSelect={async (id) => {
                    await selectThread(id);
                    closeSidebar();
                  }}
                  onMutateReady={(fn) => setMutateThreads(() => fn)}
                  onInterruptCountChange={setInterruptCount}
                />
              </aside>
            </div>
          )}
          {inspector && isDesktopLayout === false && (
            <div className="absolute inset-0 z-40 flex justify-end md:hidden">
              <button
                type="button"
                aria-label="Close inspector"
                className="absolute inset-0 bg-black/40"
                onClick={closeInspector}
              />
              <aside
                aria-label="Inspector"
                className="relative z-10 h-full w-[min(22rem,calc(100vw-2.25rem))] bg-background shadow-xl"
              >
                <InspectorPanel
                  onClose={closeInspector}
                  onReportToMainChat={notifyMainChat}
                  onOpenFile={openWorkspaceFile}
                />
              </aside>
            </div>
          )}
          <ResizablePanelGroup
            direction="horizontal"
            autoSaveId="witaiscientist-chat"
          >
            {sidebar && isDesktopLayout && (
              <>
                <ResizablePanel
                  id="thread-history"
                  order={1}
                  defaultSize={23}
                  minSize={18}
                  className="relative min-w-[260px]"
                >
                  <ThreadList
                    workspaceDir={readyProject}
                    onNewChat={startNewChat}
                    onThreadSelect={selectThread}
                    onMutateReady={(fn) => setMutateThreads(() => fn)}
                    onInterruptCountChange={setInterruptCount}
                  />
                </ResizablePanel>
                <ResizableHandle />
              </>
            )}

            <ResizablePanel
              id="chat"
              className="relative flex flex-col"
              order={2}
            >
              <WorkbenchTabs
                activeView={view}
                files={openWorkspaceFiles}
                dirtyFiles={dirtyWorkspaceFiles}
                onSelect={setView}
                onCloseFile={closeWorkspaceFile}
              />
              <div className="relative min-h-0 flex-1 overflow-hidden">
                {/* Chat stays mounted across view switches. We hide it via
                  `display:none` (rather than unmounting) so flipping to
                  Skills/Memory and back is instant — no thread re-fetch, no
                  message-list rebuild, and any in-flight run keeps streaming
                  in the background. Cost is bounded: only the *current*
                  thread's state is held; no accumulation per switch. */}
                <div
                  className={cn(
                    "flex h-full min-h-0 flex-1 flex-col",
                    view !== null && "hidden"
                  )}
                >
                  <ChatProvider
                    key={chatSessionRevision}
                    activeAssistant={assistant}
                    workspaceDir={readyProject}
                    onHistoryRevalidate={() => mutateThreads?.()}
                  >
                    <ChatInterface
                      assistant={assistant}
                      runtimeConfigRevision={backendRevision}
                      onRuntimeConfigUpdated={() =>
                        setBackendRevision((revision) => revision + 1)
                      }
                      onShowAgents={showAgentsInspector}
                      onNotifyReady={(fn) => setNotifyMainChat(() => fn)}
                      onNavigate={handleDashboardNav}
                      onOpenThread={selectThread}
                      onOpenWorkspaceFile={(path) =>
                        openWorkspaceFile({ path })
                      }
                      workspaceOpen={Boolean(
                        inspector && inspectorTab !== "agents"
                      )}
                    />
                  </ChatProvider>
                </div>
                {view === "files" && (
                  <div className="h-full overflow-y-auto p-3 sm:p-4">
                    <WorkspacePanel onOpenFile={openWorkspaceFile} />
                  </div>
                )}
                {view === "skills" && <SkillsMarketplace />}
                {view === "memory" && (
                  <MemoryPanel
                    initialTab={
                      memoryTab as
                        | "identity"
                        | "knowledge"
                        | "history"
                        | null
                        | undefined
                    }
                    initialObsId={memoryObs}
                    initialExecId={memoryExec}
                  />
                )}
                {openWorkspaceFiles.map((file) => {
                  const active = view === workspaceFileView(file.path);
                  return (
                    <div
                      key={file.path}
                      className={
                        active ? "flex h-full min-h-0 flex-col" : "hidden"
                      }
                    >
                      <WorkspaceDocument
                        path={file.path}
                        size={file.size}
                        onDirtyChange={(dirty) =>
                          setWorkspaceFileDirty(file.path, dirty)
                        }
                      />
                    </div>
                  );
                })}
              </div>
            </ResizablePanel>

            {inspector && isDesktopLayout && (
              <>
                <ResizableHandle />
                <ResizablePanel
                  id="inspector"
                  order={3}
                  defaultSize={26}
                  minSize={20}
                  className="relative min-w-[300px]"
                >
                  <InspectorPanel
                    onClose={closeInspector}
                    onReportToMainChat={notifyMainChat}
                    onOpenFile={openWorkspaceFile}
                  />
                </ResizablePanel>
              </>
            )}
          </ResizablePanelGroup>
        </div>
      </div>
    </>
  );
}

function HomePageContent() {
  const [config, setConfig] = useState<DeploymentConfig | null>(null);
  const [configInitializing, setConfigInitializing] = useState(true);
  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [assistantId, setAssistantId] = useQueryState("assistantId");

  // The backend owns the persistent provider/model profile. The browser only
  // needs a connection address, which we can recover on a fresh browser
  // profile from the local launcher rather than making the user configure it
  // again.
  useEffect(() => {
    const savedConfig = getConfig();
    if (savedConfig) {
      setConfig(savedConfig);
      if (assistantId !== savedConfig.assistantId) {
        setAssistantId(savedConfig.assistantId);
      }
      setConfigInitializing(false);
      return;
    }

    let cancelled = false;
    void fetch("/api/witaisci-config", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not detect the local backend.");
        const detectedConfig = configFromBackendStatus(await response.json());
        if (!detectedConfig) {
          throw new Error("The local backend address is unavailable.");
        }
        if (cancelled) return;
        saveConfig(detectedConfig);
        setConfig(detectedConfig);
        if (assistantId !== detectedConfig.assistantId) {
          void setAssistantId(detectedConfig.assistantId);
        }
      })
      .catch(() => {
        if (!cancelled) setConfigDialogOpen(true);
      })
      .finally(() => {
        if (!cancelled) setConfigInitializing(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL in sync with the fixed main graph. This also repairs links
  // created before the rename that still contain `assistantId=imaging_scientist`.
  useEffect(() => {
    if (config && assistantId !== config.assistantId) {
      setAssistantId(config.assistantId);
    }
  }, [config, assistantId, setAssistantId]);

  const handleSaveConfig = useCallback((newConfig: DeploymentConfig) => {
    saveConfig(newConfig);
    setConfig(newConfig);
  }, []);

  const langsmithApiKey =
    config?.langsmithApiKey || process.env.NEXT_PUBLIC_LANGSMITH_API_KEY || "";

  if (!config) {
    if (configInitializing) {
      return (
        <div className="flex h-screen items-center justify-center">
          <p className="text-muted-foreground">Connecting to Imaging Scientist...</p>
        </div>
      );
    }
    return (
      <>
        <ConfigDialog
          open={configDialogOpen}
          onOpenChange={setConfigDialogOpen}
          onSave={handleSaveConfig}
        />
        <div className="flex h-screen items-center justify-center">
          <div className="text-center">
            <h1 className="text-2xl font-bold">Welcome to Imaging Scientist</h1>
            <p className="mt-2 text-muted-foreground">
              Configure your deployment to get started
            </p>
            <Button
              onClick={() => setConfigDialogOpen(true)}
              className="mt-4"
            >
              Open Configuration
            </Button>
          </div>
        </div>
      </>
    );
  }

  return (
    <ClientProvider
      deploymentUrl={config.deploymentUrl}
      apiKey={langsmithApiKey}
    >
      <HomePageInner
        config={config}
        configDialogOpen={configDialogOpen}
        setConfigDialogOpen={setConfigDialogOpen}
        handleSaveConfig={handleSaveConfig}
      />
    </ClientProvider>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center">
          <p className="text-muted-foreground">Loading…</p>
        </div>
      }
    >
      <HomePageContent />
    </Suspense>
  );
}
