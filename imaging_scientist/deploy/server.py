"""``ImagingSci deploy`` — start a standalone langgraph dev server.

Hosts the fully-equipped imaging_scientist main agent (MCP + async sub-agents)
for consumption by external LangChain-compatible UIs (deep-agents-ui,
agent-chat-ui, LangSmith Studio) and SDK clients.

Differs from ``ImagingSci`` / ``ImagingSci serve``: no in-process CLI agent,
no session DB, no channel runtime, no TUI. The terminal only shows
startup progress, the Ready banner, and then blocks until Ctrl+C.

Mode dispatch happens via the ``WITAISCIENTIST_DEPLOY_MODE`` env var
injected by ``start_langgraph_dev``: ``full`` for the deploy subprocess
(this command), ``stripped`` for CLI/serve subprocesses, unset for the
parent process. The subprocess reads this at module-load time
(``langgraph_dev/manager.py``) to flip ``_ASYNC_SUBAGENTS_AVAILABLE``,
and the agent build code (``imaging_scientist.py:_get_default_agent``)
loads or skips MCP based on the value.
"""

from __future__ import annotations

import atexit
import os
import signal
import threading
from pathlib import Path
from typing import Any

import typer  # type: ignore[import-untyped]
from rich.panel import Panel
from rich.text import Text

from ..cli._app import app
from ..stream.console import console

_PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google-genai": "GOOGLE_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "zhipu-code": "ZHIPU_API_KEY",
    "volcengine": "VOLCENGINE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "dashscope-code": "DASHSCOPE_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "kimi-coding": "KIMI_API_KEY",
    "custom-openai": "CUSTOM_OPENAI_API_KEY",
    "custom-anthropic": "CUSTOM_ANTHROPIC_API_KEY",
}


def _provider_credential_error(config: Any) -> str | None:
    """Return an actionable deploy-time configuration error, when needed.

    Onboarding intentionally permits empty keys because a deployment may supply
    them through environment variables.  Validate the *effective* environment
    here, after ``apply_config_to_env``, before LangGraph imports the graph.
    """
    provider = str(getattr(config, "provider", "")).strip().lower()
    if not provider or provider == "ollama":
        return None
    if provider == "anthropic" and getattr(config, "anthropic_auth_mode", "") == "oauth":
        return None
    if provider == "openai" and getattr(config, "openai_auth_mode", "") == "oauth":
        return None

    env_name = _PROVIDER_API_KEY_ENV.get(provider)
    if not env_name:
        return f"Unsupported LLM provider in configuration: {provider!r}."
    if not os.environ.get(env_name, "").strip():
        return (
            f"No API key is configured for provider '{provider}'. "
            f"Set {env_name} in the deployment configuration or rerun onboard."
        )

    if provider == "custom-openai" and not os.environ.get(
        "CUSTOM_OPENAI_BASE_URL", ""
    ).strip():
        return (
            "No base URL is configured for provider 'custom-openai'. "
            "Set CUSTOM_OPENAI_BASE_URL in the deployment configuration or rerun onboard."
        )
    if provider == "custom-anthropic" and not os.environ.get(
        "CUSTOM_ANTHROPIC_BASE_URL", ""
    ).strip():
        return (
            "No base URL is configured for provider 'custom-anthropic'. "
            "Set CUSTOM_ANTHROPIC_BASE_URL in the deployment configuration or rerun onboard."
        )
    return None


@app.command()
def deploy(
    workdir: str | None = typer.Option(
        None,
        "--workdir",
        help="Workspace directory (default: config.default_workdir or cwd)",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Port for langgraph dev (default: config.langgraph_dev_port = 6174)",
    ),
    tunnel: bool = typer.Option(
        False,
        "--tunnel",
        help="Expose the server over a public Cloudflare tunnel (no auth — "
        "anyone with the URL can drive the agent; trusted use only)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
):
    """Deploy imaging_scientist main agent as a standalone LangGraph dev server.

    Starts ``langgraph dev`` in deploy mode (full MCP + async sub-agents).
    Connect any LangChain-compatible UI or SDK client to the printed
    endpoint. Press Ctrl+C to stop.
    """
    from ..config import apply_config_to_env, get_effective_config
    from ..langgraph_dev.manager import (
        _DEFAULT_PORT,
        RUNTIME,
        _is_port_occupied,
        _wait_for_port_release,
        is_langgraph_dev_running,
        mark_workspace_supervisor,
        pop_workspace_switch_request,
        read_tunnel_url,
        start_langgraph_dev,
        stop_langgraph_dev,
    )

    # 1. Load config (no CLI overrides here — deploy is opinionated about
    # full MCP + async; user-facing flags are workspace/port/debug only).
    cli_overrides: dict[str, Any] = {}
    if debug:
        cli_overrides["log_level"] = "DEBUG"
    config = get_effective_config(cli_overrides)
    if debug:
        os.environ["WITAISCIENTIST_LOG_LEVEL"] = "DEBUG"
        from ..cli.commands import _configure_logging

        _configure_logging()
    apply_config_to_env(config)
    credential_error = _provider_credential_error(config)
    if credential_error:
        console.print(f"[red]Deployment configuration error:[/red] {credential_error}")
        raise typer.Exit(1)

    # 2. Resolve workspace (CLI > config.default_workdir > deployment data dir).
    # A bare deploy uses the installation's `data` directory instead of the
    # shell's current directory, while --workdir remains fully user-controlled.
    if workdir:
        ws = os.path.abspath(os.path.expanduser(workdir))
    elif config.default_workdir:
        ws = os.path.abspath(os.path.expanduser(config.default_workdir))
    else:
        ws = os.path.join(os.getcwd(), "data")
    # Subprocess inherits this path via WITAISCIENTIST_WORKSPACE_DIR (set inside
    # start_langgraph_dev). Ensure the dir exists; do NOT mutate the parent
    # process's paths module state — the deploy parent has no in-process agent.
    os.makedirs(ws, exist_ok=True)

    # 3. Resolve port (explicit None check — don't treat --port 0 as "unset"),
    # then validate range so misconfigurations fail fast with a clear message
    # instead of an opaque socket error from langgraph dev later.
    effective_port = (
        int(getattr(config, "langgraph_dev_port", _DEFAULT_PORT))
        if port is None
        else port
    )
    if not (1 <= effective_port <= 65535):
        console.print(
            f"[red]Invalid port {effective_port}. Use an integer in [1, 65535].[/red]"
        )
        raise typer.Exit(1)

    # 4. Pre-flight port check — refuse to start if a non-ImagingSci process is
    # holding the port. If an existing ImagingSci langgraph dev is already up,
    # also refuse (deploy is the "primary server" — running multiple on the
    # same port is a configuration error).
    if _is_port_occupied(effective_port):
        if is_langgraph_dev_running(port=effective_port):
            console.print(
                f"[red]Port {effective_port} is already serving a langgraph dev "
                f"instance.[/red]"
            )
            console.print(
                "[dim]Stop the existing ImagingSci/serve session first, or use "
                "[bold]--port[/bold] to deploy on a different port.[/dim]"
            )
        else:
            console.print(
                f"[red]Port {effective_port} is occupied by another process.[/red]"
            )
            console.print(
                f"[dim]Run [bold]lsof -i :{effective_port}[/bold] to inspect, "
                f"or use [bold]--port[/bold] to pick a different port.[/dim]"
            )
        raise typer.Exit(1)

    # 5. Startup banner
    _auth_label = _describe_auth(config)
    console.print(
        Panel(
            Text.from_markup(
                f"[bold]Workspace:[/bold] {_shorten(ws)}\n"
                f"[bold]Port:[/bold]      {effective_port}\n"
                f"[bold]Auth:[/bold]      {_auth_label}"
            ),
            title="[bold cyan]Imaging Scientist Deploy[/bold cyan]",
            border_style="cyan",
        )
    )
    if config.dangerous_mode:
        from ..cli._constants import (
            DANGEROUS_BANNER_LABEL,
            DANGEROUS_BANNER_MESSAGE,
        )

        console.print(
            f"[bold white on red] ⚠ {DANGEROUS_BANNER_LABEL} [/bold white on red] "
            f"[bold red]{DANGEROUS_BANNER_MESSAGE}[/bold red]"
        )

    if tunnel:
        console.print(
            "[bold white on red] ⚠ PUBLIC TUNNEL [/bold white on red] "
            "[bold red]Public URL, no auth — share only with people you "
            "trust.[/bold red]"
        )

    # 6. ccproxy lifecycle (only if any provider uses OAuth)
    _ccproxy_proc = None
    if config.anthropic_auth_mode == "oauth" or config.openai_auth_mode == "oauth":
        try:
            from ..ccproxy_manager import maybe_start_ccproxy, stop_ccproxy

            with console.status(
                "[dim]Starting ccproxy (OAuth proxy)...[/dim]", spinner="dots"
            ):
                _ccproxy_proc = maybe_start_ccproxy(config)
            if _ccproxy_proc:
                atexit.register(stop_ccproxy, _ccproxy_proc)
                console.print("[green]✓[/green] ccproxy started")
        except RuntimeError as exc:
            console.print(f"[red]ccproxy startup failed:[/red] {exc}")
            raise typer.Exit(1) from exc

    # 7. Start langgraph dev (deploy mode → full MCP + async)
    jobs_per_worker = int(getattr(config, "langgraph_dev_jobs_per_worker", 10))
    file_persistence = bool(getattr(config, "langgraph_dev_file_persistence", True))
    try:
        with console.status(
            "[dim]Starting langgraph dev (deploy mode: MCP + async)...[/dim]",
            spinner="dots",
        ):
            proc = start_langgraph_dev(
                workspace_dir=Path(ws),
                port=effective_port,
                file_persistence=file_persistence,
                jobs_per_worker=jobs_per_worker,
                deploy_mode=True,
                tunnel=tunnel,
            )
        atexit.register(stop_langgraph_dev, proc)
    except Exception as exc:
        console.print(f"[red]langgraph dev startup failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    # start_langgraph_dev already health-polled before returning; if we got
    # here, the subprocess is up.
    console.print("[green]✓[/green] langgraph dev ready")
    mark_workspace_supervisor(True)
    atexit.register(mark_workspace_supervisor, False)
    console.print(
        f"[dim]Workspace switching enabled: {RUNTIME.workspace_supervisor}[/dim]"
    )

    # 8b. Cloudflare tunnel URL — the local server is healthy, but cloudflared
    # establishes the public tunnel a few seconds later and prints the random
    # URL into the log. Poll for it so we can surface it in the ready banner.
    public_url: str | None = None
    if tunnel:
        with console.status(
            "[dim]Waiting for Cloudflare tunnel URL...[/dim]", spinner="dots"
        ):
            public_url = read_tunnel_url()
        if public_url:
            console.print("[green]✓[/green] tunnel up")
        else:
            console.print(
                "[yellow]⚠ Tunnel URL not detected within the wait window. "
                f"Check the log ({_shorten(str(RUNTIME.log_file))}) for a "
                "trycloudflare.com URL.[/yellow]"
            )

    # 9. Ready banner
    log_hint = _shorten(str(RUNTIME.log_file))
    public_line = f"[bold]Public URL:[/bold]   {public_url}\n" if public_url else ""
    console.print(
        Panel(
            Text.from_markup(
                f"[bold]Endpoint:[/bold]     "
                f"http://localhost:{effective_port}\n"
                f"{public_line}"
                f"[bold]Assistant ID:[/bold] AIScientist\n"
                f"[bold]Connect via:[/bold]  any LangChain SDK / "
                f"LangGraph-compatible UI\n"
                f"[bold]Logs:[/bold]         {log_hint}\n\n"
                f"[dim]Press Ctrl+C to stop.[/dim]"
            ),
            title="[bold green]✓ Ready[/bold green]",
            border_style="green",
        )
    )

    # 10. Block on signal — mirror serve's dual-gate (threading.Event +
    # explicit SIGINT/SIGTERM handlers) so SIGTERM (no default raise) also
    # triggers clean shutdown.
    shutdown_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: Any) -> None:
        shutdown_event.set()
        if signum == signal.SIGINT:
            signal.default_int_handler(signum, _frame)

    _orig_sigint = signal.signal(signal.SIGINT, _handle_shutdown)
    _orig_sigterm = signal.signal(signal.SIGTERM, _handle_shutdown)

    try:
        while not shutdown_event.is_set():
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
                stop_langgraph_dev(proc)
                _wait_for_port_release(effective_port)
                try:
                    proc = start_langgraph_dev(
                        workspace_dir=requested_workspace,
                        port=effective_port,
                        file_persistence=file_persistence,
                        jobs_per_worker=jobs_per_worker,
                        deploy_mode=True,
                        tunnel=tunnel,
                    )
                    ws = str(requested_workspace)
                    atexit.register(stop_langgraph_dev, proc)
                    console.print(
                        f"[green]Workspace ready:[/green] {_shorten(ws)}"
                    )
                except Exception as exc:
                    console.print(
                        f"[red]Workspace switch failed:[/red] {exc}. "
                        "Restoring the previous workspace."
                    )
                    _wait_for_port_release(effective_port)
                    proc = start_langgraph_dev(
                        workspace_dir=previous_workspace,
                        port=effective_port,
                        file_persistence=file_persistence,
                        jobs_per_worker=jobs_per_worker,
                        deploy_mode=True,
                        tunnel=tunnel,
                    )
                    ws = str(previous_workspace)
                    atexit.register(stop_langgraph_dev, proc)
            shutdown_event.wait(timeout=0.1)
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        mark_workspace_supervisor(False)
        signal.signal(signal.SIGINT, _orig_sigint)
        signal.signal(signal.SIGTERM, _orig_sigterm)
        # stop_langgraph_dev + stop_ccproxy run via atexit during interpreter
        # shutdown, so subprocess teardown happens AFTER this print returns.
        # Don't claim "Stopped." here — that would be a lie until atexit fires.
        console.print(
            "\n[dim]Shutting down (background cleanup may take a few seconds)...[/dim]"
        )


def _describe_auth(config: Any) -> str:
    """Render a one-line auth summary for the startup banner."""
    anth = getattr(config, "anthropic_auth_mode", "api_key")
    oai = getattr(config, "openai_auth_mode", "api_key")
    if anth == "oauth" and oai == "oauth":
        return "OAuth (Anthropic + OpenAI via ccproxy)"
    if anth == "oauth":
        return "OAuth (Anthropic via ccproxy) + API key (OpenAI)"
    if oai == "oauth":
        return "API key (Anthropic) + OAuth (OpenAI via ccproxy)"
    return "API key"


def _shorten(path: str) -> str:
    """Replace ``$HOME`` prefix with ``~`` for compact display."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home) :]
    return path
