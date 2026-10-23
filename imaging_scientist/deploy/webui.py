"""``ImagingSci`` WebUI mode — deploy-style LangGraph server + browser front-end.

Selected via ``ui_backend = "webui"`` (onboard → "Select UI mode" → WebUI).
Running ``ImagingSci`` then becomes, in ONE terminal:

    ImagingSci deploy  +  WebUI front-end

i.e. start a *full* langgraph dev server (MCP + async sub-agents, exactly like
``ImagingSci deploy``) AND launch the published ``@witaiscientist/webui`` Next.js
front-end via ``npx``, so the user never needs two terminals.

Design boundary: this module deliberately REUSES the low-level
``start_langgraph_dev`` primitive but does **not** import, call, or modify the
``deploy`` command. ``ImagingSci deploy`` stays a clean, opinionated standalone
server for *external* consumers (deep-agents-ui, agent-chat-ui, LangSmith
Studio, SDK clients); WebUI mode is a separate, parallel launcher.

An editable source checkout starts its adjacent ``webui`` directory so local
front-end changes are exercised immediately. Installed packages fall back to
``npx @witaiscientist/webui@latest``.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

import typer  # type: ignore[import-untyped]
from rich.panel import Panel
from rich.text import Text

from ..stream.console import console

# Front-end npm package + spec. ``@latest`` → always the newest published UI.
_WEBUI_PACKAGE = "@witaiscientist/webui@latest"
_DEFAULT_WEBUI_PORT = 4716


def _find_local_webui_dir() -> Path | None:
    """Return the adjacent WebUI source directory for an editable checkout."""
    candidate = Path(__file__).resolve().parents[2] / "webui"
    if (candidate / "package.json").is_file():
        return candidate
    return None


def run_webui(config: Any, workspace_dir: str | None = None) -> None:
    """Start the deploy-style backend + the WebUI front-end, then block.

    Args:
        config: Effective ``ImagingScientistConfig`` (already env-applied upstream,
            but re-applied here so this is safe to call standalone).
        workspace_dir: Resolved workspace path; falls back to
            ``config.default_workdir`` then cwd.

    Blocks until Ctrl+C / SIGTERM, or until the front-end process exits, then
    tears down both subprocesses. Never returns a value.
    """
    from ..config import apply_config_to_env
    from ..langgraph_dev.manager import (
        _DEFAULT_PORT,
        RUNTIME,
        _is_port_occupied,
        _read_workspace_sidecar,
        _wait_for_port_release,
        is_langgraph_dev_running,
        mark_workspace_supervisor,
        pop_workspace_switch_request,
        start_langgraph_dev,
        stop_langgraph_dev,
    )

    apply_config_to_env(config)

    # 1. Resolve workspace (CLI-resolved value > config.default_workdir > data),
    # mirroring `ImagingSci deploy`. The langgraph dev subprocess inherits this via
    # WITAISCIENTIST_WORKSPACE_DIR (set inside start_langgraph_dev).
    if workspace_dir:
        ws = os.path.abspath(os.path.expanduser(workspace_dir))
    elif getattr(config, "default_workdir", ""):
        ws = os.path.abspath(os.path.expanduser(config.default_workdir))
    else:
        ws = os.path.join(os.getcwd(), "data")
    os.makedirs(ws, exist_ok=True)

    # 2. Resolve ports: backend = langgraph dev (browser connects here),
    # webui_port = the local Next.js server the browser actually opens.
    backend_port = int(getattr(config, "langgraph_dev_port", _DEFAULT_PORT))
    webui_port = int(getattr(config, "webui_port", _DEFAULT_WEBUI_PORT))
    for label, p in (("langgraph dev", backend_port), ("WebUI", webui_port)):
        if not (1 <= p <= 65535):
            console.print(
                f"[red]Invalid {label} port {p}. Use an integer in [1, 65535].[/red]"
            )
            raise typer.Exit(1)
    if webui_port == backend_port:
        # Same port → the backend would claim it first and npx would fail to
        # bind. Catch it here with a clear message instead of a cryptic error.
        console.print(
            f"[red]WebUI port and langgraph dev port must differ "
            f"(both are {webui_port}).[/red]"
        )
        console.print(
            "[dim]Change one with [bold]ImagingSci config set webui_port <port>"
            "[/bold].[/dim]"
        )
        raise typer.Exit(1)

    # 3. Pre-flight the Node front-end requirement BEFORE starting the server,
    # so a missing toolchain fails fast with actionable guidance.
    npx = shutil.which("npx")
    if not npx:
        console.print(
            Panel(
                Text.from_markup(
                    "[bold]Node.js / npx was not found on PATH.[/bold]\n\n"
                    "The WebUI front-end requires [bold]npx[/bold] from "
                    "Node.js.\n\n"
                    "Install [bold]Node.js 24 LTS[/bold] (which includes npx), "
                    "then re-run [bold]ImagingSci[/bold] — or switch UI modes with "
                    "[bold]ImagingSci config set ui_backend tui[/bold]."
                ),
                title="[bold red]WebUI unavailable[/bold red]",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    # 4. Backend (langgraph dev): reuse an ImagingSci server already on the port,
    # else start a fresh deploy-mode one (full MCP + async). Refuse a foreign
    # occupant — that's a configuration error, not something to silently share.
    started_proc = None
    jobs_per_worker = int(getattr(config, "langgraph_dev_jobs_per_worker", 10))
    file_persistence = bool(getattr(config, "langgraph_dev_file_persistence", True))
    if _is_port_occupied(backend_port):
        if is_langgraph_dev_running(port=backend_port):
            # Reuse an existing ImagingSci server only when it serves THIS workspace
            # — mirror the sidecar guard in ensure_langgraph_dev so WebUI started
            # from workspace B never silently binds to a server pinned to
            # workspace A. No sidecar (older subprocess) → reuse, as before.
            sidecar = _read_workspace_sidecar()
            if (
                sidecar is not None
                and Path(sidecar["workspace"]).resolve() != Path(ws).resolve()
            ):
                console.print(
                    f"[red]Port {backend_port} is already serving a langgraph "
                    f"dev for a different workspace "
                    f"({_shorten(sidecar['workspace'])}).[/red]"
                )
                console.print(
                    f"[dim]Stop that ImagingSci session, or launch from that "
                    f"workspace ([bold]--workdir {sidecar['workspace']}[/bold])."
                    f"[/dim]"
                )
                raise typer.Exit(1)
            console.print(
                f"[green]✓[/green] Reusing langgraph dev already serving "
                f"port {backend_port}"
            )
        else:
            console.print(
                f"[red]Port {backend_port} is occupied by another process.[/red]"
            )
            console.print(
                f"[dim]Free it (lsof -i :{backend_port}) or change it with "
                f"[bold]ImagingSci config set langgraph_dev_port <port>[/bold].[/dim]"
            )
            raise typer.Exit(1)
    else:
        try:
            with console.status(
                "[dim]Starting langgraph dev (deploy mode: MCP + async)...[/dim]",
                spinner="dots",
            ):
                started_proc = start_langgraph_dev(
                    workspace_dir=Path(ws),
                    port=backend_port,
                    file_persistence=file_persistence,
                    jobs_per_worker=jobs_per_worker,
                    deploy_mode=True,
                )
            atexit.register(stop_langgraph_dev, started_proc)
        except Exception as exc:
            console.print(f"[red]langgraph dev startup failed:[/red] {exc}")
            raise typer.Exit(1) from exc
        console.print("[green]✓[/green] langgraph dev ready")

    if started_proc is not None:
        mark_workspace_supervisor(True)
        atexit.register(mark_workspace_supervisor, False)

    if _is_port_occupied(webui_port):
        console.print(
            f"[yellow]⚠ Port {webui_port} is already in use; the WebUI server "
            f"may fail to start. Change it with "
            f"[bold]ImagingSci config set webui_port <port>[/bold].[/yellow]"
        )

    # 5. Launch the front-end in its own process group so the whole tree
    # tears down cleanly on shutdown. An editable checkout must use its local
    # source rather than an older npm release, otherwise backend graph renames
    # and local UI fixes can get out of sync.
    local_webui_dir = _find_local_webui_dir()
    if local_webui_dir is not None:
        next_executable = (
            local_webui_dir
            / "node_modules"
            / ".bin"
            / ("next.cmd" if os.name == "nt" else "next")
        )
        if not next_executable.is_file():
            console.print(
                f"[red]Local WebUI dependencies are missing at "
                f"{_shorten(str(local_webui_dir))}.[/red]"
            )
            console.print(
                "[dim]Run [bold]npm install[/bold] in that directory, then "
                "start ImagingSci again.[/dim]"
            )
            raise typer.Exit(1)
        webui_command = [
            str(next_executable),
            "dev",
            "--turbopack",
            "--port",
            str(webui_port),
        ]
        webui_cwd: str | None = str(local_webui_dir)
        frontend_status = (
            f"[dim]Starting local WebUI source at "
            f"{_shorten(str(local_webui_dir))}…[/dim]"
        )
    else:
        webui_command = [npx, "--yes", _WEBUI_PACKAGE, "--port", str(webui_port)]
        webui_cwd = None
        frontend_status = (
            f"[dim]Fetching {_WEBUI_PACKAGE} via npx (first run may take a "
            f"moment)…  Press Ctrl+C to stop.[/dim]"
        )

    # WITAISCIENTIST_LANGGRAPH_DEV_PORT lets the UI's config prefill point at
    # our backend automatically. Secrets are scrubbed — the browser UI never
    # needs LLM provider API keys.
    webui_env = _scrubbed_env(
        {
            "WITAISCIENTIST_LANGGRAPH_DEV_PORT": str(backend_port),
            "PORT": str(webui_port),
        }
    )
    console.print(
        Panel(
            Text.from_markup(
                f"[bold]Backend:[/bold]  http://localhost:{backend_port}  "
                f"[dim](langgraph dev — Assistant: AIScientist)[/dim]\n"
                f"[bold]WebUI:[/bold]    http://localhost:{webui_port}  "
                f"[dim](opens in your browser)[/dim]\n"
                f"[bold]Logs:[/bold]     {_shorten(str(RUNTIME.log_file))}\n\n"
                + frontend_status
            ),
            title="[bold green]✓ AIScientist WebUI[/bold green]",
            border_style="green",
        )
    )

    popen_kwargs: dict[str, Any] = {"env": webui_env}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        # New process group so the npx → node → next subtree can be killed as a
        # unit by taskkill /T in _stop_webui.
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        if webui_cwd is not None:
            popen_kwargs["cwd"] = webui_cwd
        webui_proc = subprocess.Popen(webui_command, **popen_kwargs)
    except Exception as exc:
        console.print(f"[red]Failed to launch WebUI:[/red] {exc}")
        raise typer.Exit(1) from exc
    atexit.register(_stop_webui, webui_proc)

    # 6. Block on signal — same dual-gate as `ImagingSci deploy` (threading.Event +
    # explicit SIGINT/SIGTERM handlers). Also exit if the front-end dies on its
    # own (e.g. the user closes it), so we don't leave the backend orphaned.
    shutdown_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        shutdown_event.set()
        if signum == signal.SIGINT:
            signal.default_int_handler(signum, _frame)

    _orig_sigint = signal.signal(signal.SIGINT, _handle_shutdown)
    _orig_sigterm = signal.signal(signal.SIGTERM, _handle_shutdown)

    try:
        while not shutdown_event.is_set():
            if webui_proc.poll() is not None:
                console.print("\n[dim]WebUI server exited.[/dim]")
                break
            if started_proc is not None:
                requested_workspace = pop_workspace_switch_request()
                if (
                    requested_workspace is not None
                    and requested_workspace != Path(ws).resolve()
                ):
                    previous_workspace = Path(ws).resolve()
                    console.print(
                        f"\n[cyan]Switching workspace:[/cyan] "
                        f"{_shorten(str(requested_workspace))}"
                    )
                    stop_langgraph_dev(started_proc)
                    _wait_for_port_release(backend_port)
                    try:
                        started_proc = start_langgraph_dev(
                            workspace_dir=requested_workspace,
                            port=backend_port,
                            file_persistence=file_persistence,
                            jobs_per_worker=jobs_per_worker,
                            deploy_mode=True,
                        )
                        ws = str(requested_workspace)
                        atexit.register(stop_langgraph_dev, started_proc)
                        console.print(
                            f"[green]Workspace ready:[/green] {_shorten(ws)}"
                        )
                    except Exception as exc:
                        console.print(
                            f"[red]Workspace switch failed:[/red] {exc}. "
                            "Restoring the previous workspace."
                        )
                        _wait_for_port_release(backend_port)
                        started_proc = start_langgraph_dev(
                            workspace_dir=previous_workspace,
                            port=backend_port,
                            file_persistence=file_persistence,
                            jobs_per_worker=jobs_per_worker,
                            deploy_mode=True,
                        )
                        ws = str(previous_workspace)
                        atexit.register(stop_langgraph_dev, started_proc)
            shutdown_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        if started_proc is not None:
            mark_workspace_supervisor(False)
        signal.signal(signal.SIGINT, _orig_sigint)
        signal.signal(signal.SIGTERM, _orig_sigterm)
        _stop_webui(webui_proc)
        # stop_langgraph_dev (if we started it) runs via atexit during
        # interpreter shutdown — don't claim "Stopped." before that fires.
        console.print(
            "\n[dim]Shutting down (background cleanup may take a few seconds)...[/dim]"
        )


def _stop_webui(proc: subprocess.Popen) -> None:
    """Terminate the WebUI process tree (idempotent)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        elif os.name == "nt":
            # taskkill /T terminates the whole child tree (node + next server).
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _scrubbed_env(extra: dict[str, str]) -> dict[str, str]:
    """Inherit the parent environment minus secrets, then apply ``extra``.

    The WebUI is a browser client that only talks to the local langgraph server
    — it has no use for LLM provider API keys. Stripping credential-bearing
    variables keeps them out of the npx-fetched front-end package and its
    transitive npm dependencies (defence-in-depth, especially with ``@latest``).
    Names are matched loosely (``*_KEY`` / ``*API_KEY*`` / ``*TOKEN*`` /
    ``*SECRET*`` / ``*PASSWORD*``); node/npm essentials (PATH, HOME, NODE_*,
    npm_*, proxies, CA certs) carry none of these and pass through untouched.
    """
    secret_hints = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
    env = {
        k: v
        for k, v in os.environ.items()
        if not (
            k.upper().endswith("_KEY")
            or any(hint in k.upper() for hint in secret_hints)
        )
    }
    env.update(extra)
    return env


def _shorten(path: str) -> str:
    """Replace ``$HOME`` prefix with ``~`` for compact display."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home) :]
    return path
