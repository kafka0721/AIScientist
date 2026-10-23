"""Configuration management for imaging_scientist.

Handles loading, saving, and merging configuration from multiple sources
with the following priority (highest to lowest):
    CLI arguments > Environment variables > Config file > Defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_type_hints

import yaml
from dotenv import dotenv_values, find_dotenv

# Tools that run shell commands and need manual HITL approval (subject to
# shell_allow_list). Single source of truth for every interrupt consumer
# (stream/display.py, channels/consumer.py) — keep aligned with the agent's
# `interrupt_on` set in imaging_scientist.py.
HITL_SHELL_TOOLS = ("execute", "run_in_background")


class MemoryObservationTarget(StrEnum):
    """Runtime locations that can receive `record_observation`."""

    AGENT = "agent"
    TURN_WORKER = "turn_worker"
    SUBAGENT_WORKER = "subagent_worker"


class MemoryObservationWriter(StrEnum):
    """Configured observation-writing policy."""

    OFF = "off"
    AGENT = "agent"
    WORKER = "worker"
    ALL = "all"

    def enables(self, target: MemoryObservationTarget) -> bool:
        match self:
            case MemoryObservationWriter.OFF:
                return False
            case MemoryObservationWriter.AGENT:
                return target == MemoryObservationTarget.AGENT
            case MemoryObservationWriter.WORKER:
                return target in (
                    MemoryObservationTarget.TURN_WORKER,
                    MemoryObservationTarget.SUBAGENT_WORKER,
                )
            case MemoryObservationWriter.ALL:
                return target in (
                    MemoryObservationTarget.AGENT,
                    MemoryObservationTarget.TURN_WORKER,
                    MemoryObservationTarget.SUBAGENT_WORKER,
                )


class MemorySkillSynthesisMode(StrEnum):
    """Configured AutoSkills approval behavior."""

    REVIEW = "review"
    AUTO = "auto"


class MemorySkillSynthesisCadence(StrEnum):
    """Preset cadence for the built-in AutoSkills schedule."""

    NIGHTLY = "nightly"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


DEFAULT_MEMORY_OBSERVATION_WRITER = MemoryObservationWriter.ALL
DEFAULT_MEMORY_SKILL_SYNTHESIS_MODE = MemorySkillSynthesisMode.REVIEW
DEFAULT_MEMORY_SKILL_SYNTHESIS_CADENCE = MemorySkillSynthesisCadence.WEEKLY
DEFAULT_MEMORY_SKILL_SYNTHESIS_TIME = "03:00"


def _normalize_hhmm(value: Any) -> str | None:
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        return None
    hour, minute = parts
    if not (hour.isdecimal() and minute.isdecimal()):
        return None
    try:
        hour_int = int(hour)
        minute_int = int(minute)
    except ValueError:
        return None
    if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
        return None
    return f"{hour_int:02d}:{minute_int:02d}"


# =============================================================================
# Configuration paths
# =============================================================================


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Uses XDG_CONFIG_HOME if set, otherwise ~/.config/witaiscientist/
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "witaiscientist"
    return Path.home() / ".config" / "witaiscientist"


def get_config_path() -> Path:
    """Get the path to the configuration file."""
    override = os.environ.get("WITAISCIENTIST_CONFIG_PATH", "").strip()
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override)))
    return get_config_dir() / "config.yaml"


# =============================================================================
# Configuration dataclass
# =============================================================================


@dataclass
class ImagingScientistConfig:
    """imaging_scientist configuration settings.

    Attributes:
        anthropic_api_key: Anthropic API key for Claude models.
        openai_api_key: OpenAI API key for GPT models.
        nvidia_api_key: NVIDIA API key for NVIDIA models.
        google_api_key: Google API key for Gemini models.
        tavily_api_key: Tavily API key for web search.
        provider: Default LLM provider ('anthropic', 'openai', 'google-genai', or 'nvidia').
        model: Default model name (short name or full ID).
        auxiliary_provider: Provider for auxiliary_model (empty = use main provider).
        auxiliary_model: Model for memory workers + tool selector (empty = use main model).
        default_mode: Default workspace mode ('daemon' or 'run').
        default_workdir: Default workspace directory (empty = use current working directory).
        show_thinking: Whether to show thinking panels in CLI.
    """

    # API Keys
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_auth_mode: str = "api_key"  # "api_key" | "oauth"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_auth_mode: str = "api_key"  # "api_key" | "oauth"
    nvidia_api_key: str = ""
    google_api_key: str = ""
    minimax_api_key: str = ""
    minimax_base_url: str = ""
    siliconflow_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""
    volcengine_api_key: str = ""
    dashscope_api_key: str = ""
    moonshot_api_key: str = ""
    kimi_api_key: str = ""
    custom_openai_api_key: str = ""
    custom_openai_base_url: str = ""
    custom_anthropic_api_key: str = ""
    custom_anthropic_base_url: str = ""
    ollama_base_url: str = ""
    tavily_api_key: str = ""

    # LLM Settings
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    model_fallbacks: str = ""  # "model:provider,model:provider" fallback chain
    # Optional auxiliary model for background/helper LLM calls (memory workers +
    # tool selector). Empty = fall back to the main model/provider.
    auxiliary_provider: str = ""  # empty = use main provider
    auxiliary_model: str = ""  # empty = use main model
    # Opt-in compatibility profile for custom OpenAI gateways; never disables verification.
    gateway_tls_profile: str = "default"  # default | x25519
    gateway_proxy: str = ""  # Explicit HTTP(S) proxy for gateway clients; empty uses environment.

    # Independent rebuttal agent. Empty model/provider values reuse the main
    # chat model client, but the agent always receives a fresh, explicit
    # context with no EvoMemory middleware.
    enable_rebuttal_agent: bool = True
    # Alibaba Qwen uses provider="dashscope", model="qwen-*", and
    # DASHSCOPE_API_KEY through its OpenAI-compatible endpoint.
    rebuttal_provider: str = ""  # empty = use main provider
    rebuttal_model: str = ""  # empty = use main model

    # Async Sub-agent Settings
    # When True (default), the ImagingSci CLI auto-starts a langgraph dev subprocess
    # so any sub-agent flagged ``async: true`` in subagents/<name>.yaml runs
    # non-blocking via AsyncSubAgent. Currently affects writing-agent and
    # data-analysis-agent. Adds ~10-15s to CLI startup (langgraph dev cold
    # start, mostly MCP server spawn time).
    #
    # Set False to run fully in-process — saves the startup cost in scenarios
    # where async isn't useful: short scripted ImagingSci runs (CI / one-shot
    # ``-p "..."``), low-RAM environments, or workflows that only need the
    # synchronous sub-agents (planner / research / code / debug).
    enable_async_subagents: bool = True

    # Port for the auto-started langgraph dev subprocess. 6174 is Kaprekar's
    # constant — a memorable imaging_scientist-themed default that avoids collisions
    # with common dev ports (3000/5000/8000/8080) and the langgraph CLI default
    # 2024. Override if it conflicts with another local service.
    langgraph_dev_port: int = 6174

    # Port for the WebUI front-end (Next.js server from @witaiscientist/webui),
    # used only when ui_backend == "webui". 4716 is 6174 reversed — a memorable
    # pairing with the langgraph dev port that it connects to. The backend keeps
    # its own port (langgraph_dev_port); this is just the browser server.
    webui_port: int = 4716

    # Default IANA timezone for internal AutoSkills maintenance schedules.
    # Empty string => the host's local IANA zone (resolved via tzlocal), falling
    # back to UTC if it can't be determined; set e.g. "Europe/London" to pin one.
    scheduler_default_timezone: str = ""

    # Whether langgraph dev persists its runtime state to .langgraph_api/ next
    # to the subprocess cwd. True (default) keeps async-task and
    # Store API state across subprocess restarts — useful for future
    # cross-session async and Store features. Set False to suppress
    # writes (workspace stays cleaner; state is in-memory only and lost on
    # CLI exit). imaging_scientist's main thread persistence uses sessions.db
    # regardless of this setting.
    langgraph_dev_file_persistence: bool = True

    # Concurrency: how many runs each langgraph dev worker processes in parallel.
    # 10 is the langgraph dev recommended default and works well on a typical
    # dev machine. Lower it (e.g., 4) on memory-constrained or low-core
    # machines if multiple async sub-agents in flight cause noticeable
    # slowdown.
    langgraph_dev_jobs_per_worker: int = 10

    # Max LangGraph super-steps (LLM call / tool call / sub-agent delegation
    # each count as 1) before raising GraphRecursionError. Resets on every
    # ``agent.invoke()`` — i.e., this is per-turn, NOT per-conversation. For
    # long conversations the relevant mechanisms are checkpointer persistence
    # (sessions.db), ContextEditingMiddleware (window management), and
    # EvoMemoryMiddleware (cross-turn memory).
    #
    # 1,000,000 is "effectively unlimited" — typical research turns use
    # 200-1000 steps; reaching 1M would cost ~$10K in tokens, by which point
    # rate limits, context overflow, or API quota errors would trip first.
    # Lower (e.g., 5000) if you want a tighter safety net against runaway loops.
    recursion_limit: int = 1_000_000

    # Memory Settings
    # Profile memory injects and maintains `/memories/profile/...` files.
    memory_profile_enabled: bool = True
    # Observation memory indexes `/memories/observations/...` and adds
    # observation-read guidance/context. Writes require this switch plus an
    # allowed `memory_observation_writer` role below.
    memory_observations_enabled: bool = True
    # Which observation-writing path receives the `record_observation` tool:
    # "off" disables writes; "agent" means live agents; "worker" means
    # post-run memory workers; "all" means live agents and post-run memory
    # workers.
    memory_observation_writer: MemoryObservationWriter = (
        DEFAULT_MEMORY_OBSERVATION_WRITER
    )
    # Post-turn and post-subagent memory workers. Disable for no-background-memory
    # controls while still allowing live agents to read configured memory.
    memory_workers_enabled: bool = True
    # Slow EvoMemory maintenance that periodically scans observation clusters
    # and drafts reusable skills.
    memory_skill_synthesis_enabled: bool = True
    memory_skill_synthesis_mode: MemorySkillSynthesisMode = (
        DEFAULT_MEMORY_SKILL_SYNTHESIS_MODE
    )
    memory_skill_synthesis_cadence: MemorySkillSynthesisCadence = (
        DEFAULT_MEMORY_SKILL_SYNTHESIS_CADENCE
    )
    memory_skill_synthesis_time: str = DEFAULT_MEMORY_SKILL_SYNTHESIS_TIME

    # Workspace Settings
    default_mode: Literal["daemon", "run"] = "daemon"
    default_workdir: str = ""

    # UI Settings
    show_thinking: bool = True
    # "webui" launches the browser front-end (@witaiscientist/webui via npx) +
    # a deploy-style langgraph server instead of the in-terminal CLI/TUI.
    ui_backend: Literal["cli", "tui", "webui"] = "tui"
    log_level: str = "warning"
    reasoning_effort: str = "high"
    # Anthropic prompt caching for OpenRouter anthropic/* models. Opt out if
    # cache-write costs outweigh the benefit for a workflow.
    openrouter_anthropic_prompt_cache: bool = True

    # Channel Settings
    channel_enabled: str = ""  # "imessage" | "telegram" | "discord" | "slack" | "wechat" | "dingtalk" | "feishu" | "email" | "qq" | "signal" | "" (comma-separated for multiple)
    channel_send_thinking: bool = True  # forward thinking to any channel
    channel_debug_tracing: bool = False  # emit extra inbound diagnostics at DEBUG
    require_mention: str = "group"  # "always" | "group" | "off"
    text_chunk_limit: int = 0  # 0 = use capability default
    allowed_channels: str = ""  # comma-separated channel IDs, empty = allow all

    # iMessage Settings
    imessage_enabled: bool = False  # legacy compat
    imessage_allowed_senders: str = ""

    # Telegram Settings
    telegram_bot_token: str = ""
    telegram_allowed_senders: str = ""
    telegram_proxy: str = ""

    # Discord Settings
    discord_bot_token: str = ""
    discord_allowed_senders: str = ""
    discord_allowed_channels: str = ""
    discord_proxy: str = ""

    # Slack Settings
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_allowed_senders: str = ""
    slack_allowed_channels: str = ""
    slack_proxy: str = ""

    # Feishu Settings
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_webhook_port: int = 9000
    feishu_allowed_senders: str = ""
    feishu_domain: str = "https://open.feishu.cn"
    feishu_proxy: str = ""
    feishu_subscription_mode: str = "webhook"  # "webhook" | "websocket"

    # WeChat Settings
    wechat_backend: str = "wecom"
    wechat_webhook_port: int = 9001
    wechat_allowed_senders: str = ""
    wechat_proxy: str = ""
    wechat_wecom_corp_id: str = ""
    wechat_wecom_agent_id: str = ""
    wechat_wecom_secret: str = ""
    wechat_wecom_token: str = ""
    wechat_wecom_encoding_aes_key: str = ""
    wechat_mp_app_id: str = ""
    wechat_mp_app_secret: str = ""
    wechat_mp_token: str = ""
    wechat_mp_encoding_aes_key: str = ""
    # Personal WeChat (iLink Bot) — credentials obtained via QR-code login.
    # Run: python -m imaging_scientist.channels.wechat.serve --qr-login
    wechat_personal_account_id: str = ""
    wechat_personal_token: str = ""
    wechat_personal_base_url: str = ""
    wechat_personal_cdn_base_url: str = ""
    wechat_personal_dm_policy: str = "open"
    wechat_personal_group_policy: str = "disabled"
    wechat_personal_group_allowed: str = ""

    # DingTalk Settings
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    dingtalk_allowed_senders: str = ""
    dingtalk_proxy: str = ""

    # Email Settings
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_imap_username: str = ""
    email_imap_password: str = ""
    email_imap_mailbox: str = "INBOX"
    email_imap_use_ssl: bool = True
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_use_tls: bool = True
    email_from_address: str = ""
    email_poll_interval: int = 30
    email_mark_seen: bool = True
    email_max_body_chars: int = 12000
    email_subject_prefix: str = "Re: "
    email_allowed_senders: str = ""

    # QQ Settings
    qq_app_id: str = ""
    qq_app_secret: str = ""
    qq_allowed_senders: str = ""

    # Signal Settings
    signal_phone_number: str = ""
    signal_cli_path: str = "signal-cli"
    signal_config_dir: str = ""
    signal_allowed_senders: str = ""
    signal_rpc_port: int = 7583

    # Shared webhook port (0 = disabled)
    shared_webhook_port: int = 9000

    # HITL (Human-in-the-Loop) Settings
    auto_approve: bool = False  # Auto-approve all tool executions without prompting
    auto_mode: bool = False  # Run unattended: imply auto_approve and disable ask_user
    shell_allow_list: str = ""  # Comma-separated shell command prefixes to auto-approve

    # Dangerous mode: real-filesystem access (no workspace confinement). The agent
    # operates on real absolute paths anywhere on disk; the privileged-command
    # blocklist (sudo/chmod/dd/...) still applies. Implies auto_approve.
    dangerous_mode: bool = False

    # Agent features
    enable_ask_user: bool = True  # Enable ask_user tool for agent-initiated questions

    # CodeInterpreterMiddleware (PTC — Parallel Tool Calls) tuning
    # The PTC allowlist itself is hardcoded in
    # ``imaging_scientist/middleware/code_interpreter.py`` as a load-bearing safety
    # decision (excludes ``execute`` so PTC can't bypass HITL approval,
    # excludes ``write_file``/``edit_file`` because batched writes have no
    # benefit). Only the resource budget knobs are user-tunable.
    code_interpreter_timeout: float = 60.0  # seconds per JS eval
    code_interpreter_max_result_chars: int = 10000  # truncate large JSON results

    # Default per-command timeout (seconds) for the sandbox `execute` tool.
    # Only the default — the agent can still override per command up to the
    # deepagents max_execute_timeout cap (3600s).
    sandbox_execute_timeout: int = 300

    # Checkpoint pruning (sessions.db retention per (thread_id, checkpoint_ns))
    # Safety net for runaway conversations. Under DeltaChannel (deepagents 0.6+)
    # normal usage produces linear growth, so this default is set well above
    # any realistic conversation length (~180-450 turns of dialogue) while
    # still capping legacy bloat at upgrade time. 0 disables ongoing pruning
    # entirely; the one-time legacy migration sweep still runs.
    checkpoint_keep_per_thread: int = 1000

    # DM access control policy
    dm_policy: str = "allowlist"

    # OpenAI API mode - "" = auto, "true" = force Responses, "false" = force Completions
    use_responses_api: str = ""

    # ccproxy
    ccproxy_port: int = 8000

    # STT (Speech-to-Text) Settings
    stt_enabled: bool = False
    stt_language: str = "auto"  # "auto" | "zh" | "en"
    stt_model: str = ""  # override model id; empty = auto-select by language
    stt_device: str = "cpu"  # "cpu" | "cuda"
    stt_compute_type: str = "int8"  # "int8" | "float16" | "float32"

    # Domain-EMA Settings (Domain-Enhanced Memory Adaptation).
    # When ``domain_ema_enabled`` is true, the subagent memory worker runs an
    # extra distillation middleware that writes structured M_I / M_E entries
    # under ``/memories/observations/domain/<domain>/<role>/``. Default off so
    # legacy projects are unaffected.
    domain_ema_enabled: bool = False
    domain_ema_domain: str = "generic"  # "its" | "bio" | "generic"
    domain_ema_write_threshold: float = 0.2  # min utility_score for M_E writes

    def __post_init__(self) -> None:
        # A non-positive or non-int sandbox_execute_timeout (e.g. a hand-edited
        # config file value — load_config does not coerce file values — or a
        # 0/negative env value) would raise inside CustomSandboxBackend.__init__
        # and crash agent/CLI startup. Fall back to the default instead, matching
        # how malformed env values already degrade to defaults.
        t = self.sandbox_execute_timeout
        if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
            logging.getLogger(__name__).warning(
                "Invalid sandbox_execute_timeout %r; falling back to 300.", t
            )
            self.sandbox_execute_timeout = 300

        # Dangerous mode implies auto_approve regardless of source (CLI, env,
        # config file). Mirrors how auto_mode implies auto_approve — done here so
        # the coupling holds even when dangerous_mode is set via `config set`.
        if self.dangerous_mode:
            self.auto_approve = True

        _normalize_str_enum_fields(self)

        synthesis_time = _normalize_hhmm(self.memory_skill_synthesis_time)
        if synthesis_time is None:
            logging.getLogger(__name__).warning(
                "Invalid memory_skill_synthesis_time %r; falling back to %s.",
                self.memory_skill_synthesis_time,
                DEFAULT_MEMORY_SKILL_SYNTHESIS_TIME,
            )
            self.memory_skill_synthesis_time = DEFAULT_MEMORY_SKILL_SYNTHESIS_TIME
        else:
            self.memory_skill_synthesis_time = synthesis_time


@dataclass(frozen=True)
class MemoryControls:
    """Resolved memory feature switches used by agent and worker wiring."""

    profile_enabled: bool
    observations_enabled: bool
    observation_writer: MemoryObservationWriter
    workers_enabled: bool

    @classmethod
    def from_config(cls, config: ImagingScientistConfig) -> MemoryControls:
        return cls(
            profile_enabled=config.memory_profile_enabled,
            observations_enabled=config.memory_observations_enabled,
            observation_writer=config.memory_observation_writer,
            workers_enabled=config.memory_workers_enabled,
        )

    @property
    def memory_enabled(self) -> bool:
        return self.profile_enabled or self.observations_enabled

    def observation_tool_enabled(self, target: MemoryObservationTarget) -> bool:
        return self.observations_enabled and self.observation_writer.enables(target)

    def worker_needed(self, target: MemoryObservationTarget) -> bool:
        if not self.workers_enabled:
            return False
        match target:
            case MemoryObservationTarget.TURN_WORKER:
                return self.profile_enabled or self.observation_tool_enabled(target)
            case MemoryObservationTarget.SUBAGENT_WORKER:
                return self.profile_enabled or self.observation_tool_enabled(target)
            case MemoryObservationTarget.AGENT:
                return False


# =============================================================================
# Config file operations
# =============================================================================


def load_config() -> ImagingScientistConfig:
    """Load configuration from file.

    Returns:
        ImagingScientistConfig instance with values from file, or defaults if
        file doesn't exist.
    """
    config_path = get_config_path()

    if not config_path.exists():
        return ImagingScientistConfig()

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Filter to only valid fields
        valid_fields = {f.name for f in fields(ImagingScientistConfig)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return ImagingScientistConfig(**filtered_data)
    except Exception:
        # On any error, return defaults
        return ImagingScientistConfig()


def save_config(config: ImagingScientistConfig) -> None:
    """Save configuration to file.

    Args:
        config: ImagingScientistConfig instance to save.
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        config_path.parent.chmod(0o700)
    except OSError:
        pass

    data = _config_to_dict(config)

    # Save all fields including empty API keys (users can set them via env vars instead)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    try:
        config_path.chmod(0o600)
    except OSError:
        pass


def reset_config() -> None:
    """Reset configuration to defaults by deleting the config file."""
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()


def _config_to_dict(config: ImagingScientistConfig) -> dict[str, Any]:
    """Return a plain serializable config dict."""
    return {key: _plain_config_value(value) for key, value in asdict(config).items()}


# =============================================================================
# Config value operations
# =============================================================================


def _coerce_value(value: Any, field_type: Any) -> Any:
    """Coerce a value to the expected field type.

    Args:
        value: The value to coerce.
        field_type: The target type (from dataclass field).

    Returns:
        The coerced value.

    Raises:
        ValueError: If the value cannot be coerced.
        TypeError: If the value cannot be coerced.
    """
    if _is_str_enum_type(field_type):
        return field_type(str(value).strip().lower())
    if field_type == "bool" or field_type is bool:
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    if field_type == "int" or field_type is int:
        return int(value)
    if field_type == "float" or field_type is float:
        return float(value)
    return str(value)


def _plain_config_value(value: Any) -> Any:
    """Return the persisted/user-facing representation for a config value."""
    return value.value if isinstance(value, StrEnum) else value


@lru_cache(maxsize=1)
def _config_field_types() -> dict[str, Any]:
    """Return resolved dataclass annotations for config fields."""
    return get_type_hints(ImagingScientistConfig)


def _config_field_type(key: str, fallback: Any) -> Any:
    """Return the resolved dataclass annotation for a config field."""
    return _config_field_types().get(key, fallback)


def _is_str_enum_type(field_type: Any) -> bool:
    return isinstance(field_type, type) and issubclass(field_type, StrEnum)


def _normalize_str_enum_fields(config: ImagingScientistConfig) -> None:
    """Normalize all StrEnum config fields, falling back to field defaults."""
    for field in fields(config):
        field_type = _config_field_type(field.name, field.type)
        if not _is_str_enum_type(field_type):
            continue

        raw_value = getattr(config, field.name)
        try:
            value = _coerce_value(raw_value, field_type)
        except (ValueError, TypeError):
            default = field.default
            logging.getLogger(__name__).warning(
                "Invalid %s %r; falling back to %s.",
                field.name,
                raw_value,
                _plain_config_value(default),
            )
            value = default
        setattr(config, field.name, value)


def get_config_value(key: str) -> Any:
    """Get a single configuration value.

    Args:
        key: Configuration key name.

    Returns:
        The value, or None if key doesn't exist.
    """
    config = load_config()
    value = getattr(config, key, None)
    return _plain_config_value(value)


def set_config_value(key: str, value: Any) -> bool:
    """Set a single configuration value.

    Args:
        key: Configuration key name.
        value: New value.

    Returns:
        True if successful, False if key is invalid.
    """
    valid_fields = {f.name for f in fields(ImagingScientistConfig)}
    if key not in valid_fields:
        return False

    config = load_config()

    # Type coercion based on field type
    field_info = next(f for f in fields(ImagingScientistConfig) if f.name == key)
    field_type = _config_field_type(key, field_info.type)

    # __post_init__ only clamps on load, so validate here too. Reject bool before coercion
    # (_coerce_value(True, int) would turn it into 1 and slip past).
    if key == "sandbox_execute_timeout" and isinstance(value, bool):
        return False

    try:
        value = _coerce_value(value, field_type)
    except (ValueError, TypeError):
        return False

    if key == "sandbox_execute_timeout" and value <= 0:
        return False
    if key == "memory_skill_synthesis_time":
        value = _normalize_hhmm(value)
        if value is None:
            return False

    setattr(config, key, value)
    save_config(config)
    return True


def list_config() -> dict[str, Any]:
    """List all configuration values.

    Returns:
        Dictionary of all configuration key-value pairs.
    """
    return _config_to_dict(load_config())


# =============================================================================
# Effective configuration (merging sources)
# =============================================================================

# Environment variable mappings
_ENV_MAPPINGS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "anthropic_base_url": "ANTHROPIC_BASE_URL",
    "anthropic_auth_mode": "WITAISCIENTIST_ANTHROPIC_AUTH_MODE",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_base_url": "OPENAI_BASE_URL",
    "openai_auth_mode": "WITAISCIENTIST_OPENAI_AUTH_MODE",
    "nvidia_api_key": "NVIDIA_API_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "minimax_api_key": "MINIMAX_API_KEY",
    "minimax_base_url": "MINIMAX_BASE_URL",
    "siliconflow_api_key": "SILICONFLOW_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "zhipu_api_key": "ZHIPU_API_KEY",
    "volcengine_api_key": "VOLCENGINE_API_KEY",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "moonshot_api_key": "MOONSHOT_API_KEY",
    "kimi_api_key": "KIMI_API_KEY",
    "custom_openai_api_key": "CUSTOM_OPENAI_API_KEY",
    "custom_openai_base_url": "CUSTOM_OPENAI_BASE_URL",
    "custom_anthropic_api_key": "CUSTOM_ANTHROPIC_API_KEY",
    "custom_anthropic_base_url": "CUSTOM_ANTHROPIC_BASE_URL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "tavily_api_key": "TAVILY_API_KEY",
    "default_mode": "WITAISCIENTIST_DEFAULT_MODE",
    "default_workdir": "WITAISCIENTIST_WORKSPACE_DIR",
    "ui_backend": "WITAISCIENTIST_UI_BACKEND",
    "log_level": "WITAISCIENTIST_LOG_LEVEL",
    "model_fallbacks": "WITAISCIENTIST_MODEL_FALLBACKS",
    "auxiliary_provider": "WITAISCIENTIST_AUXILIARY_PROVIDER",
    "auxiliary_model": "WITAISCIENTIST_AUXILIARY_MODEL",
    "enable_rebuttal_agent": "WITAISCIENTIST_ENABLE_REBUTTAL_AGENT",
    "rebuttal_provider": "WITAISCIENTIST_REBUTTAL_PROVIDER",
    "rebuttal_model": "WITAISCIENTIST_REBUTTAL_MODEL",
    "reasoning_effort": "WITAISCIENTIST_REASONING_EFFORT",
    "openrouter_anthropic_prompt_cache": (
        "WITAISCIENTIST_OPENROUTER_ANTHROPIC_PROMPT_CACHE"
    ),
    "dangerous_mode": "WITAISCIENTIST_DANGEROUS_MODE",
    "channel_debug_tracing": "WITAISCIENTIST_CHANNEL_DEBUG_TRACING",
    "ccproxy_port": "WITAISCIENTIST_CCPROXY_PORT",
    "use_responses_api": "WITAISCIENTIST_USE_RESPONSES_API",
    "checkpoint_keep_per_thread": "WITAISCIENTIST_CHECKPOINT_KEEP_PER_THREAD",
    "enable_async_subagents": "WITAISCIENTIST_ENABLE_ASYNC_SUBAGENTS",
    "langgraph_dev_port": "WITAISCIENTIST_LANGGRAPH_DEV_PORT",
    "webui_port": "WITAISCIENTIST_WEBUI_PORT",
    "scheduler_default_timezone": "WITAISCIENTIST_SCHEDULER_DEFAULT_TIMEZONE",
    "code_interpreter_timeout": "WITAISCIENTIST_CODE_INTERPRETER_TIMEOUT",
    "code_interpreter_max_result_chars": "WITAISCIENTIST_CODE_INTERPRETER_MAX_RESULT_CHARS",
    "sandbox_execute_timeout": "WITAISCIENTIST_SANDBOX_EXECUTE_TIMEOUT",
    "langgraph_dev_file_persistence": "WITAISCIENTIST_LANGGRAPH_DEV_FILE_PERSISTENCE",
    "langgraph_dev_jobs_per_worker": "WITAISCIENTIST_LANGGRAPH_DEV_JOBS_PER_WORKER",
    "recursion_limit": "WITAISCIENTIST_RECURSION_LIMIT",
    "memory_profile_enabled": "WITAISCIENTIST_MEMORY_PROFILE_ENABLED",
    "memory_observations_enabled": "WITAISCIENTIST_MEMORY_OBSERVATIONS_ENABLED",
    "memory_observation_writer": "WITAISCIENTIST_MEMORY_OBSERVATION_WRITER",
    "memory_workers_enabled": "WITAISCIENTIST_MEMORY_WORKERS_ENABLED",
    "memory_skill_synthesis_enabled": "WITAISCIENTIST_MEMORY_SKILL_SYNTHESIS_ENABLED",
    "memory_skill_synthesis_mode": "WITAISCIENTIST_MEMORY_SKILL_SYNTHESIS_MODE",
    "memory_skill_synthesis_cadence": "WITAISCIENTIST_MEMORY_SKILL_SYNTHESIS_CADENCE",
    "memory_skill_synthesis_time": "WITAISCIENTIST_MEMORY_SKILL_SYNTHESIS_TIME",
    "domain_ema_enabled": "WITAISCIENTIST_DOMAIN_EMA_ENABLED",
    "domain_ema_domain": "WITAISCIENTIST_DOMAIN_EMA_DOMAIN",
    "domain_ema_write_threshold": "WITAISCIENTIST_DOMAIN_EMA_WRITE_THRESHOLD",
}

# API settings saved through the WebUI must survive a launcher restart.  A
# repository .env is useful as an initial default, but it must not silently
# replace a provider key or endpoint that the user saved later in config.yaml.
_PERSISTED_CONNECTION_FIELDS = frozenset(
    key
    for key in _ENV_MAPPINGS
    if key.endswith("_api_key") or key.endswith("_base_url")
)


def get_effective_config(
    cli_overrides: dict[str, Any] | None = None,
) -> ImagingScientistConfig:
    """Get effective configuration by merging all sources.

    Priority (highest to lowest):
        1. CLI arguments (cli_overrides)
        2. Environment variables
        3. Config file
        4. Defaults

    Args:
        cli_overrides: Dictionary of CLI argument overrides.

    Returns:
        ImagingScientistConfig with merged values.
    """
    # Start with file config (includes defaults for missing values)
    config = load_config()
    data = _config_to_dict(config)

    # Read .env without mutating os.environ.  Mutating it made a stale project
    # key indistinguishable from an explicit shell override and caused the
    # local WebUI's saved API configuration to appear to reset on every start.
    dotenv_path = find_dotenv(usecwd=True)
    dotenv = dotenv_values(dotenv_path) if dotenv_path else {}

    # Explicit process environment remains higher priority than config.yaml.
    # Values found only in .env are fallback defaults for connection settings:
    # the durable WebUI profile wins whenever it already has a value.
    for config_key, env_key in _ENV_MAPPINGS.items():
        env_value = os.environ.get(env_key)
        if not env_value and not (
            config_key in _PERSISTED_CONNECTION_FIELDS and data.get(config_key)
        ):
            dotenv_value = dotenv.get(env_key)
            env_value = dotenv_value if isinstance(dotenv_value, str) else None
        if env_value:
            field_info = next(
                f for f in fields(ImagingScientistConfig) if f.name == config_key
            )
            try:
                data[config_key] = _coerce_value(
                    env_value,
                    _config_field_type(config_key, field_info.type),
                )
            except (ValueError, TypeError):
                pass

    # Apply CLI overrides (highest priority)
    if cli_overrides:
        for key, value in cli_overrides.items():
            if value is not None and key in data:
                data[key] = value

    return ImagingScientistConfig(**data)


def apply_config_to_env(config: ImagingScientistConfig) -> None:
    """Apply config API keys to environment variables if not already set.

    This allows the config file to provide API keys that downstream
    libraries (like langchain-anthropic) can pick up.

    Args:
        config: Configuration to apply.
    """
    if config.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = config.anthropic_api_key
    if config.anthropic_base_url and not os.environ.get("ANTHROPIC_BASE_URL"):
        os.environ["ANTHROPIC_BASE_URL"] = config.anthropic_base_url
    if config.openai_api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = config.openai_api_key
    if config.openai_base_url and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = config.openai_base_url
    if config.nvidia_api_key and not os.environ.get("NVIDIA_API_KEY"):
        os.environ["NVIDIA_API_KEY"] = config.nvidia_api_key
    if config.google_api_key and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = config.google_api_key
    if config.minimax_api_key and not os.environ.get("MINIMAX_API_KEY"):
        os.environ["MINIMAX_API_KEY"] = config.minimax_api_key
    if config.minimax_base_url and not os.environ.get("MINIMAX_BASE_URL"):
        os.environ["MINIMAX_BASE_URL"] = config.minimax_base_url
    if config.siliconflow_api_key and not os.environ.get("SILICONFLOW_API_KEY"):
        os.environ["SILICONFLOW_API_KEY"] = config.siliconflow_api_key
    if config.openrouter_api_key and not os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = config.openrouter_api_key
    if config.deepseek_api_key and not os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = config.deepseek_api_key
    if config.zhipu_api_key and not os.environ.get("ZHIPU_API_KEY"):
        os.environ["ZHIPU_API_KEY"] = config.zhipu_api_key
    if config.volcengine_api_key and not os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["VOLCENGINE_API_KEY"] = config.volcengine_api_key
    if config.dashscope_api_key and not os.environ.get("DASHSCOPE_API_KEY"):
        os.environ["DASHSCOPE_API_KEY"] = config.dashscope_api_key
    if config.moonshot_api_key and not os.environ.get("MOONSHOT_API_KEY"):
        os.environ["MOONSHOT_API_KEY"] = config.moonshot_api_key
    if config.kimi_api_key and not os.environ.get("KIMI_API_KEY"):
        os.environ["KIMI_API_KEY"] = config.kimi_api_key
    if config.custom_openai_api_key and not os.environ.get("CUSTOM_OPENAI_API_KEY"):
        os.environ["CUSTOM_OPENAI_API_KEY"] = config.custom_openai_api_key
    if config.custom_openai_base_url and not os.environ.get("CUSTOM_OPENAI_BASE_URL"):
        os.environ["CUSTOM_OPENAI_BASE_URL"] = config.custom_openai_base_url
    if config.custom_anthropic_api_key and not os.environ.get(
        "CUSTOM_ANTHROPIC_API_KEY"
    ):
        os.environ["CUSTOM_ANTHROPIC_API_KEY"] = config.custom_anthropic_api_key
    if config.custom_anthropic_base_url and not os.environ.get(
        "CUSTOM_ANTHROPIC_BASE_URL"
    ):
        os.environ["CUSTOM_ANTHROPIC_BASE_URL"] = config.custom_anthropic_base_url
    if config.ollama_base_url and not os.environ.get("OLLAMA_BASE_URL"):
        os.environ["OLLAMA_BASE_URL"] = config.ollama_base_url
    if config.tavily_api_key and not os.environ.get("TAVILY_API_KEY"):
        os.environ["TAVILY_API_KEY"] = config.tavily_api_key
    if config.reasoning_effort and not os.environ.get("WITAISCIENTIST_REASONING_EFFORT"):
        os.environ["WITAISCIENTIST_REASONING_EFFORT"] = config.reasoning_effort
    if not config.openrouter_anthropic_prompt_cache and not os.environ.get(
        "WITAISCIENTIST_OPENROUTER_ANTHROPIC_PROMPT_CACHE"
    ):
        os.environ["WITAISCIENTIST_OPENROUTER_ANTHROPIC_PROMPT_CACHE"] = "false"
    # Round-trip dangerous_mode to env so it survives a fresh get_effective_config()
    # (warning banner, run_in_background) and is inherited by the langgraph dev
    # subprocess — otherwise a --dangerous CLI flag (not persisted to file/env)
    # is invisible to those consumers while the backend is already unconfined.
    # Bidirectional: clear it when off so a re-apply with a lower config (or a
    # stale value) can't leave the process stuck in dangerous mode.
    if config.dangerous_mode:
        os.environ["WITAISCIENTIST_DANGEROUS_MODE"] = "true"
    else:
        os.environ.pop("WITAISCIENTIST_DANGEROUS_MODE", None)
    if config.use_responses_api and not os.environ.get(
        "WITAISCIENTIST_USE_RESPONSES_API"
    ):
        os.environ["WITAISCIENTIST_USE_RESPONSES_API"] = config.use_responses_api
