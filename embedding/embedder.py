"""임베딩 — BGE-M3 (명세 2.3).

dense(의미검색)와 sparse(키워드검색)를 한 번의 인코딩으로 함께 얻어
2.4의 하이브리드 검색에 그대로 쓴다.
모델 로딩이 무겁기 때문에 프로세스당 한 번만 만들어 재사용한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EmbedResult:
    dense: list[list[float]]
    sparse: list[dict[str, float]]  # {토큰 id: 가중치}


class Embedder:
    """BGE-M3 래퍼. 실제 모델은 첫 인코딩 때 로딩한다."""

    def __init__(self, model_name: str | None = None, use_fp16: bool | None = None):
        s = get_settings()
        self.model_name = model_name or s.embed_model
        self.use_fp16 = s.embed_use_fp16 if use_fp16 is None else use_fp16
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # 지연 임포트

            logger.info("임베딩 모델 로딩: %s", self.model_name)
            self._model = BGEM3FlagModel(self.model_name, use_fp16=self.use_fp16)
        return self._model

    def encode(self, texts: list[str], batch_size: int = 8) -> EmbedResult:
        if not texts:
            return EmbedResult(dense=[], sparse=[])

        out = self.model.encode(
            texts,
            batch_size=batch_size,
            return_dense=True,
            return_sparse=True,
        )
        dense = [list(map(float, v)) for v in out["dense_vecs"]]
        sparse = [{str(k): float(v) for k, v in w.items()} for w in out["lexical_weights"]]
        return EmbedResult(dense=dense, sparse=sparse)

    def encode_query(self, query: str) -> tuple[list[float], dict[str, float]]:
        r = self.encode([query])
        return r.dense[0], r.sparse[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()


def embed_texts(texts: list[str]):
    """명세 2.3의 호출 형태를 그대로 유지한 얇은 래퍼."""
    r = get_embedder().encode(texts)
    return r.dense, r.sparse
