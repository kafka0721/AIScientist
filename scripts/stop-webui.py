"""Stop only the imaging_scientist WebUI processes rooted in this repository."""

from __future__ import annotations

import os
import sys

import psutil


def normalize(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).lower()


def belongs_to_stack(process: psutil.Process, repo_root: str) -> bool:
    try:
        command = " ".join(process.cmdline()).lower()
        cwd = normalize(process.cwd())
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False

    if cwd == repo_root and (
        "-m witaiscientist deploy" in command
        or "-m imaging_scientist deploy" in command
    ):
        return True
    if repo_root not in command:
        return False
    return (
        ("-m witaiscientist deploy" in command or "-m imaging_scientist deploy" in command)
        or "langgraph.exe dev" in command
        or f"{repo_root}\\webui\\dist\\server.js" in command
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: stop-webui.py <repository-root>", file=sys.stderr)
        return 2

    repo_root = normalize(sys.argv[1])
    matches = [
        process
        for process in psutil.process_iter(["pid", "name"])
        if belongs_to_stack(process, repo_root)
    ]
    if not matches:
        print("No running imaging_scientist services were found.")
        return 0

    stopped = 0
    failed = False
    for process in matches:
        try:
            print(f"  Stopping {process.name()} (PID {process.pid})...")
            process.terminate()
            stopped += 1
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            print(f"  Could not stop PID {process.pid}: {exc}", file=sys.stderr)
            failed = True

    _, alive = psutil.wait_procs(matches, timeout=5)
    for process in alive:
        try:
            print(f"  Force stopping {process.name()} (PID {process.pid})...")
            process.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            print(f"  Could not force stop PID {process.pid}: {exc}", file=sys.stderr)
            failed = True

    print(f"Stopped {stopped} imaging_scientist process(es).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
