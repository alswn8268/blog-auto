"""RAGAS 평가 이력과 회귀 감지 (명세 7장 1단계 '상시 평가').

평가를 한 번 돌리고 끝내면 "지금 점수가 좋은지"만 알 수 있다. 이력을 남기면
"지난번보다 나빠졌는지"를 알 수 있고, 그래야 프롬프트·청킹·검색 파라미터를
바꿨을 때 그게 개선인지 퇴보인지 판별된다.

각 실행마다 점수와 함께 **설정 스냅샷**을 남긴다. 나중에 점수 차이를 봤을 때
무엇이 달라져서 그런지 되짚을 수 있어야 하기 때문이다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import get_settings

logger = logging.getLogger(__name__)

# 이 폭 이상 떨어지면 회귀로 본다. 평가 자체의 흔들림(LLM 판정 편차)을 감안한 값.
REGRESSION_TOLERANCE = 0.05

FAITHFULNESS_TARGET = 0.75


def config_snapshot() -> dict:
    """점수와 함께 남길 설정. 이 값이 다르면 점수를 직접 비교하면 안 된다."""
    s = get_settings()
    return {
        "prompt_version": s.prompt_version,
        "llm_model": s.llm_model,
        "embed_model": s.embed_model,
        "rerank_model": s.rerank_model,
        "fusion": s.fusion,
        "retrieve_top_k": s.retrieve_top_k,
        "rerank_top_k": s.rerank_top_k,
        "prefetch_multiplier": s.prefetch_multiplier,
        "multi_query_n": s.multi_query_n,
        "routing_enabled": s.routing_enabled,
    }


def append_run(scores: dict[str, float], n_questions: int, path: str | Path | None = None) -> dict:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "n_questions": n_questions,
        "scores": {k: round(float(v), 4) for k, v in scores.items()},
        "config": config_snapshot(),
    }
    p = Path(path or get_settings().eval_history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_history(path: str | Path | None = None) -> list[dict]:
    p = Path(path or get_settings().eval_history_path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("이력에서 깨진 줄을 건너뜁니다: %s", p)
    return entries


@dataclass
class Regression:
    metric: str
    previous: float
    current: float

    @property
    def drop(self) -> float:
        return self.previous - self.current

    def __str__(self) -> str:
        return f"{self.metric}: {self.previous:.3f} → {self.current:.3f} (▼{self.drop:.3f})"


def detect_regressions(
    current: dict[str, float],
    previous: dict[str, float] | None,
    tolerance: float = REGRESSION_TOLERANCE,
) -> list[Regression]:
    """직전 실행 대비 유의미하게 떨어진 지표를 찾는다. 첫 실행이면 빈 리스트."""
    if not previous:
        return []
    found = []
    for metric, value in current.items():
        before = previous.get(metric)
        if before is None:
            continue
        if before - float(value) > tolerance:
            found.append(Regression(metric=metric, previous=float(before), current=float(value)))
    return found


def below_target(scores: dict[str, float], target: float = FAITHFULNESS_TARGET) -> bool:
    """목표치 미달 여부. 미달이면 청킹·프롬프트를 먼저 의심할 것."""
    return float(scores.get("faithfulness", 0.0)) < target


def summarize(path: str | Path | None = None, limit: int = 10) -> list[str]:
    """최근 실행을 사람이 읽을 수 있는 줄로. 관리자 화면·CLI에서 쓴다."""
    lines = []
    for e in read_history(path)[-limit:]:
        scores = " · ".join(f"{k} {v:.3f}" for k, v in e["scores"].items())
        cfg = e.get("config", {})
        tag = f"{cfg.get('prompt_version', '?')}/{cfg.get('llm_model', '?')}"
        if cfg.get("multi_query_n"):
            tag += f"/MQ{cfg['multi_query_n']}"
        if cfg.get("routing_enabled"):
            tag += "/routing"
        lines.append(f"{e['timestamp'][:16]}  n={e['n_questions']:<3}  {scores}   [{tag}]")
    return lines
