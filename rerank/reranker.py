"""리랭커 — BGE reranker v2-m3 (명세 2.5).

하이브리드 검색이 넉넉히 가져온 후보를 질문과의 관련도로 다시 정렬한다.
신뢰도 점수(4.3)에 그대로 넣을 수 있도록 0~1로 정규화한 점수를 쓴다.

참고: 한국어 특화 체크포인트가 배포되어 있다면 RERANK_MODEL 환경변수만 바꿔 시도해볼 것.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from config import get_settings

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name: str | None = None, use_fp16: bool | None = None):
        s = get_settings()
        self.model_name = model_name or s.rerank_model
        self.use_fp16 = s.embed_use_fp16 if use_fp16 is None else use_fp16
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker  # 지연 임포트

            logger.info("리랭커 로딩: %s", self.model_name)
            self._model = FlagReranker(self.model_name, use_fp16=self.use_fp16)
        return self._model

    def score(self, query: str, candidates: list[str]) -> list[float]:
        """0~1로 정규화된 관련도 점수. 후보가 하나여도 리스트로 돌려준다."""
        if not candidates:
            return []
        pairs = [[query, c] for c in candidates]
        scores = self.model.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            return [float(scores)]
        return [float(s) for s in scores]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return Reranker()


def rerank(query: str, candidates: list[str]) -> list[float]:
    """명세 2.5의 호출 형태를 그대로 유지한 얇은 래퍼."""
    return get_reranker().score(query, candidates)


def rerank_chunks(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """청크 딕셔너리 리스트를 점수 순으로 정렬하고 상위 top_k만 남긴다.

    각 청크에 rerank_score를 실어 보내 4.3 신뢰도 계산에서 바로 쓴다.
    """
    if not chunks:
        return []
    scores = rerank(query, [c["text"] for c in chunks])
    for c, s in zip(chunks, scores):
        c["rerank_score"] = s
    return sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)[:top_k]
