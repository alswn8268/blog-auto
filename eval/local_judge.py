"""RAGAS 판정기를 로컬 모델로 묶는다.

RAGAS는 기본적으로 **OpenAI를 판정 LLM으로 사용**한다. 그대로 두면 두 가지 문제가 있다.

  1. 내부망 전용이라는 전제(명세 0장)가 깨진다 — 평가할 때마다 외부 API를 호출한다.
  2. 평가 입력에는 질문·답변뿐 아니라 **근거 조항 원문**이 통째로 들어간다.
     사규 원문이 외부로 나가는 것은 감사·개인정보 관점에서 받아들이기 어렵다.

그래서 판정 LLM은 Ollama로, 임베딩은 이미 쓰고 있는 BGE-M3로 직접 물린다.
(BGE-M3는 embedding/embedder.py의 인스턴스를 재사용하므로 모델을 두 번 올리지 않는다.)
"""

from __future__ import annotations

import logging

from config import get_settings

logger = logging.getLogger(__name__)


def _chat_ollama_class():
    """ChatOllama 구현체. 신 패키지(langchain-ollama)를 우선 쓰고 없으면 구 위치로 폴백."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError:  # langchain-community 쪽은 deprecated지만 아직 동작한다
        from langchain_community.chat_models import ChatOllama
    return ChatOllama


def build_judge_llm(model: str | None = None):
    """Ollama 기반 판정 LLM (RAGAS 래퍼로 감싼 것)."""
    from ragas.llms import LangchainLLMWrapper

    s = get_settings()
    ChatOllama = _chat_ollama_class()
    return LangchainLLMWrapper(
        ChatOllama(
            model=model or s.llm_model,
            base_url=s.ollama_url,
            temperature=0.0,  # 판정은 흔들리면 안 되므로 0
        )
    )


class LocalEmbeddings:
    """BGE-M3를 LangChain Embeddings 인터페이스로 노출하는 얇은 어댑터.

    sentence-transformers를 따로 깔지 않고, 색인에 쓰던 임베더를 그대로 재사용한다.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from embedding.embedder import get_embedder

        return get_embedder().encode(list(texts)).dense

    def embed_query(self, text: str) -> list[float]:
        from embedding.embedder import get_embedder

        return get_embedder().encode_query(text)[0]


def build_judge_embeddings():
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(LocalEmbeddings())


def build_judges(model: str | None = None):
    """(llm, embeddings) 쌍. RAGAS evaluate()에 그대로 넘긴다."""
    logger.info("RAGAS 판정기를 로컬 모델로 구성합니다 (외부 API 미사용)")
    return build_judge_llm(model), build_judge_embeddings()
