"""Config loading. YAML file at XDG location with sensible defaults."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


def _expand(p: str | Path) -> Path:
    return Path(str(p)).expanduser()


class EmbedderConfig(BaseModel):
    backend: str = "sentence-transformers"
    model: str = "all-MiniLM-L6-v2"


class StoreConfig(BaseModel):
    backend: str = "chromadb"  # 'chromadb' | 'qdrant' | 'faiss'
    path: Path = Field(default_factory=lambda: _expand("~/.local/share/skills-radar/store"))
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "skills_v1"

    @field_validator("path", mode="before")
    @classmethod
    def _expand_path(cls, v: str | Path) -> Path:
        return _expand(v)


class TransportConfig(BaseModel):
    mode: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 6580
    http_path: str = "/mcp"
    stateless_http: bool = True
    json_response: bool = True


class RewriterConfig(BaseModel):
    backend: str = "none"  # 'none' | 'ollama' | 'mlx'
    model: str = "gemma4:e4b"
    url: str = "http://localhost:11434"
    timeout: float = 5.0
    enabled: bool = False


class RerankerConfig(BaseModel):
    backend: str = "none"  # 'none' | 'ollama' | 'mlx'
    model: str = "gemma4:e4b"
    url: str = "http://localhost:11434"
    timeout: float = 8.0
    enabled: bool = False


class RetrievalConfig(BaseModel):
    hybrid_weight_semantic: float = 0.7
    hybrid_weight_lexical: float = 0.3
    default_top_k: int = 5
    rewriter: RewriterConfig = Field(default_factory=RewriterConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)

    @field_validator("hybrid_weight_semantic", "hybrid_weight_lexical")
    @classmethod
    def _0_to_1(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = f"Weight must be between 0 and 1, got {v}"
            raise ValueError(msg)
        return v


class TrustConfig(BaseModel):
    default_tier: str = "user"
    trusted_paths: list[Path] = Field(default_factory=lambda: [_expand("~/.claude/skills")])

    @field_validator("trusted_paths", mode="before")
    @classmethod
    def _expand_each(cls, v: list[str | Path]) -> list[Path]:
        return [_expand(p) for p in v]


class LLMScannerConfig(BaseModel):
    """Optional LLM-based prompt-injection scanner (extends regex catalog)."""

    enabled: bool = False
    backend: str = "ollama"  # 'none' | 'ollama' | 'mlx'
    model: str = "gemma4:e4b"
    url: str = "http://localhost:11434"
    timeout: float = 6.0


class SanitizationConfig(BaseModel):
    max_skill_size_kb: int = 64
    strip_xml_tags: bool = True
    strip_live_exec: bool = False  # Only strip for non-Claude-Code clients
    # Opt-in fail-closed gate: reject UNTRUSTED skills whose body trips an
    # injection pattern at index time, instead of indexing them with warnings.
    # Default False = warn-don't-block (a regex false positive must not
    # silently drop a skill). USER/VERIFIED/TRUSTED are never auto-rejected.
    reject_untrusted_on_injection: bool = False
    llm_scanner: LLMScannerConfig = Field(default_factory=LLMScannerConfig)


class TelemetryConfig(BaseModel):
    enabled: bool = False
    db_path: Path = Field(default_factory=lambda: _expand("~/.local/share/skills-radar/stats.db"))

    @field_validator("db_path", mode="before")
    @classmethod
    def _expand_db_path(cls, v: str | Path) -> Path:
        return _expand(v)


class WatcherConfig(BaseModel):
    """File-watcher (hot-reload) toggle. Pasywny - kqueue/inotify.
    ~8 MB stałego RAMu, 0 CPU gdy nic się nie zmienia.
    CLI --watch / --no-watch overrides this setting.

    `backend: polling` swaps the native observer for watchdog's
    PollingObserver (mtime snapshot diff every `poll_interval_s`).
    Required for Docker bind mounts on macOS/Windows - VirtioFS/gRPC-FUSE
    do not propagate host inotify events into the container, so the
    native observer sits silent there. Costs one stat-scan of the tree
    per interval - size the interval to your tree.
    """

    enabled: bool = False
    debounce_ms: int = 250
    backend: str = "native"  # 'native' | 'polling'
    poll_interval_s: float = 30.0

    @field_validator("backend")
    @classmethod
    def _known_backend(cls, v: str) -> str:
        allowed = {"native", "polling"}
        if v not in allowed:
            msg = f"watcher.backend must be one of {sorted(allowed)}, got {v!r}"
            raise ValueError(msg)
        return v


class Config(BaseModel):
    # Host platform for conditional activation: 'macos' | 'linux' | 'windows'.
    # Empty = auto-detect from sys.platform. Docker deployments MUST set this
    # explicitly - inside the container auto-detect reports 'linux', not the
    # platform of the user whose skills are indexed.
    platform: str = ""
    paths: list[Path] = Field(
        default_factory=lambda: [
            _expand("~/.claude/skills"),
            _expand("~/.claude/plugins/cache/claude-plugins-official"),
        ]
    )
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    trust: TrustConfig = Field(default_factory=TrustConfig)
    sanitization: SanitizationConfig = Field(default_factory=SanitizationConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)

    @field_validator("paths", mode="before")
    @classmethod
    def _expand_paths(cls, v: list[str | Path]) -> list[Path]:
        return [_expand(p) for p in v]

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load from YAML file, or return defaults if missing."""
        if path is None:
            path = cls.default_path()
        if not path.exists():
            logger.info("No config file at %s - using defaults", path)
            return cls()
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.info("Loaded config from %s", path)
        return cls(**data)

    @staticmethod
    def default_path() -> Path:
        return _expand("~/.config/skills-radar/config.yaml")
