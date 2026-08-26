"""프로젝트 전역 설정.

모든 설정은 환경변수로 덮어쓸 수 있다(.env.example 참고).
무거운 모델·클라이언트는 여기서 만들지 않는다 — 각 모듈이 지연 로딩한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(key: str, default: str) -> Path:
    return Path(os.environ.get(key, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    # 벡터 DB
    qdrant_url: str = field(default_factory=lambda: os.environ.get("QDRANT_URL", "http://localhost:6333"))
    collection: str = field(default_factory=lambda: os.environ.get("QDRANT_COLLECTION", "gyu_law_articles"))

    # 모델
    embed_model: str = field(default_factory=lambda: os.environ.get("EMBED_MODEL", "BAAI/bge-m3"))
    rerank_model: str = field(default_factory=lambda: os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"))
    embed_use_fp16: bool = field(default_factory=lambda: _env_bool("EMBED_USE_FP16", True))
    dense_dim: int = 1024  # bge-m3 dense 차원

    # LLM
    ollama_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "qwen3:8b"))
    llm_timeout: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT", 180))

    # 검색 파라미터
    retrieve_top_k: int = field(default_factory=lambda: _env_int("RETRIEVE_TOP_K", 20))
    rerank_top_k: int = field(default_factory=lambda: _env_int("RERANK_TOP_K", 5))

    # 경로
    data_dir: Path = field(default_factory=lambda: _env_path("DATA_DIR", str(ROOT / "data" / "raw")))
    log_dir: Path = field(default_factory=lambda: _env_path("LOG_DIR", str(ROOT / "logs")))

    # 보안
    audit_salt: str = field(default_factory=lambda: os.environ.get("AUDIT_SALT", "change-me-in-production"))
    retention_days: int = field(default_factory=lambda: _env_int("RETENTION_DAYS", 90))

    # 버전 태깅 (4.5 회고적 비교)
    prompt_version: str = field(default_factory=lambda: os.environ.get("PROMPT_VERSION", "v1"))

    @property
    def audit_log_path(self) -> Path:
        return self.log_dir / "qa_audit.jsonl"

    @property
    def feedback_log_path(self) -> Path:
        return self.log_dir / "feedback.jsonl"

    @property
    def hash_store_path(self) -> Path:
        return self.data_dir.parent / "hash_store.json"


def get_settings() -> Settings:
    """설정을 매번 새로 읽는다 — 테스트에서 환경변수를 갈아끼우기 쉽도록 캐시하지 않는다."""
    return Settings()


settings = get_settings()
