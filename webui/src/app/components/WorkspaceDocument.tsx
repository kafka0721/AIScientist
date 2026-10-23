"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Copy,
  Download,
  Eye,
  FileText,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
} from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MarkdownContent } from "@/app/components/MarkdownContent";
import { workspaceFileUrl } from "@/app/components/WorkspaceFileDialog";
import { copyText } from "@/lib/clipboard";

const LANGUAGE_MAP: Record<string, string> = {
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  cpp: "cpp",
  c: "c",
  cs: "csharp",
  php: "php",
  swift: "swift",
  kt: "kotlin",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  json: "json",
  jsonl: "json",
  xml: "xml",
  html: "html",
  css: "css",
  scss: "scss",
  sql: "sql",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  ini: "ini",
  tex: "latex",
  bib: "latex",
  r: "r",
};

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"]);
const TEXT_EXTS = new Set([
  ...Object.keys(LANGUAGE_MAP),
  "txt",
  "md",
  "markdown",
  "log",
  "csv",
  "tsv",
  "cfg",
  "conf",
  "env",
  "gitignore",
]);
const MAX_INLINE_TEXT_BYTES = 2 * 1024 * 1024;

type FileKind = "text" | "image" | "pdf" | "binary";

function fileKind(ext: string): FileKind {
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (TEXT_EXTS.has(ext)) return "text";
  return "binary";
}

interface WorkspaceDocumentProps {
  path: string;
  size?: number;
  onChanged?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

export function WorkspaceDocument({
  path,
  size,
  onChanged,
  onDirtyChange,
}: WorkspaceDocumentProps) {
  const [content, setContent] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const mountedRef = useRef(true);

  const name = path.split("/").pop() || path;
  const ext = useMemo(
    () => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : ""),
    [name]
  );
  const kind = fileKind(ext);
  const tooBigForText =
    kind === "text" && size != null && size > MAX_INLINE_TEXT_BYTES;
  const editable = kind === "text" && !tooBigForText;
  const dirty = editing && content !== null && draft !== content;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const load = useCallback(async () => {
    if (kind !== "text" || tooBigForText) {
      setContent(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(workspaceFileUrl(path));
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(
          body?.error || `Failed to load file (${response.status})`
        );
      }
      const text = await response.text();
      if (!mountedRef.current) return;
      setContent(text);
      setDraft(text);
      setEditing(false);
    } catch (loadError) {
      if (mountedRef.current) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load file."
        );
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [kind, path, tooBigForText]);

  useEffect(() => {
    void load();
  }, [load, revision]);

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(workspaceFileUrl(path), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: draft }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.error || "Failed to save file.");
      if (!mountedRef.current) return;
      setContent(draft);
      setEditing(false);
      onChanged?.();
    } catch (saveError) {
      if (mountedRef.current) {
        setError(
          saveError instanceof Error
            ? saveError.message
            : "Failed to save file."
        );
      }
    } finally {
      if (mountedRef.current) setSaving(false);
    }
  };

  const refresh = () => {
    if (dirty) return;
    setRevision((value) => value + 1);
  };

  const isMarkdown = ext === "md" || ext === "markdown";
  const language = LANGUAGE_MAP[ext] || "text";

  return (
    <section className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-3 sm:px-4">
        <FileText
          className="size-4 shrink-0 text-[var(--brand)]"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <div
            className="truncate font-mono text-xs text-foreground"
            title={path}
          >
            {name}
          </div>
          <div
            className="truncate font-mono text-[10px] text-muted-foreground"
            title={path}
          >
            {path}
          </div>
        </div>
        <span className="hidden rounded border border-border bg-muted px-2 py-0.5 font-mono text-[10px] uppercase text-muted-foreground sm:inline">
          {kind === "text" ? language : kind}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          {editing ? (
            <>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={() => {
                  setDraft(content ?? "");
                  setEditing(false);
                }}
                disabled={saving}
                aria-label="Cancel editing"
                title="Preview"
              >
                <Eye className="size-4" />
              </Button>
              <Button
                size="sm"
                className="h-8 gap-1 rounded bg-[var(--brand-solid)] px-2.5 text-[var(--brand-foreground)]"
                onClick={save}
                disabled={!dirty || saving}
              >
                {saving ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Save className="size-4" />
                )}
                <span className="hidden sm:inline">Save</span>
              </Button>
            </>
          ) : (
            <>
              {editable && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={() => setEditing(true)}
                  disabled={loading || content === null}
                  aria-label="Edit file"
                  title="Edit"
                >
                  <Pencil className="size-4" />
                </Button>
              )}
              {kind === "text" && content !== null && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={() => void copyText(content)}
                  aria-label="Copy file contents"
                  title="Copy"
                >
                  <Copy className="size-4" />
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                asChild
              >
                <a
                  href={workspaceFileUrl(path, true)}
                  download={name}
                  aria-label="Download file"
                  title="Download"
                >
                  <Download className="size-4" />
                </a>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={refresh}
                disabled={loading}
                aria-label="Refresh file"
                title="Refresh"
              >
                <RefreshCw
                  className={loading ? "size-4 animate-spin" : "size-4"}
                />
              </Button>
            </>
          )}
        </div>
      </header>

      {error && (
        <p
          role="alert"
          className="border-b border-border px-4 py-2 text-xs text-destructive"
        >
          {error}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-hidden">
        {editing ? (
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={false}
            aria-label="File content"
            className="h-full w-full resize-none border-0 bg-background p-4 font-mono text-sm leading-6 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          />
        ) : kind === "image" ? (
          <ScrollArea className="h-full">
            <div className="flex min-h-full items-center justify-center p-5">
              <img
                src={workspaceFileUrl(path)}
                alt={name}
                className="max-h-full max-w-full object-contain"
              />
            </div>
          </ScrollArea>
        ) : kind === "pdf" ? (
          <iframe
            src={workspaceFileUrl(path)}
            title={name}
            className="h-full w-full border-0"
          />
        ) : kind === "binary" || tooBigForText ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <FileText className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {tooBigForText
                ? "This file is too large to preview inline."
                : "This file type cannot be previewed."}
            </p>
            <Button
              variant="outline"
              size="sm"
              asChild
            >
              <a
                href={workspaceFileUrl(path, true)}
                download={name}
              >
                <Download className="mr-1.5 size-4" />
                Download
              </a>
            </Button>
          </div>
        ) : loading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : content ? (
          <ScrollArea className="h-full">
            <div className="p-4 sm:p-6">
              {isMarkdown ? (
                <div className="mx-auto max-w-4xl">
                  <MarkdownContent content={content} />
                </div>
              ) : (
                <SyntaxHighlighter
                  language={language}
                  style={oneDark}
                  customStyle={{
                    margin: 0,
                    borderRadius: "4px",
                    fontSize: "0.8125rem",
                  }}
                  showLineNumbers
                  wrapLongLines
                >
                  {content}
                </SyntaxHighlighter>
              )}
            </div>
          </ScrollArea>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            File is empty
          </div>
        )}
      </div>
    </section>
  );
}
