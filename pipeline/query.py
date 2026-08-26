"""질의 파이프라인 — 하이브리드 검색 → 리랭커 → LLM 생성 (아키텍처 하단 흐름).

프롬프트 가드(6.2) → 검색 → 리랭킹 → 생성 → 신뢰도(4.3) → 감사로그(6.2)까지
한 번의 호출로 이어진다. Streamlit·CLI·API 어디서 불러도 같은 경로를 탄다.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from config import get_settings
from features.confidence import score_answer
from llm.generate import LLMError, ask_llm
from rerank.reranker import rerank_chunks
from security.audit_log import log_qa_event
from security.prompt_guard import guard

logger = logging.getLogger(__name__)


@dataclass
class Answer:
    question: str
    answer: str
    contexts: list[dict] = field(default_factory=list)
    confidence: str = "하"
    rerank_score: float = 0.0
    citation_ratio: float = 0.0
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    blocked: bool = False
    error: str | None = None

    @property
    def sources(self) -> list[str]:
        return [f"{c.get('doc_title', '')} {c.get('article_no', '')}".strip() for c in self.contexts]


def retrieve(question: str, role: str | None = None, client=None) -> list[dict]:
    """하이브리드 검색으로 후보를 뽑고 리랭커로 상위 k개만 남긴다.

    role을 주면 RBAC 필터(6.2)를 검색 단계에서 건다 — 화면에서 거르는 것이 아니라
    검색 자체를 좁혀야 원문이 LLM 프롬프트로 새지 않는다.
    """
    from embedding.embedder import get_embedder
    from vectordb.store import hybrid_search

    s = get_settings()
    query_filter = None
    if role:
        from security.rbac import build_permission_filter

        query_filter = build_permission_filter(role)

    dense, sparse = get_embedder().encode_query(question)
    candidates = hybrid_search(
        dense, sparse, limit=s.retrieve_top_k, query_filter=query_filter, client=client
    )
    return rerank_chunks(question, candidates, top_k=s.rerank_top_k)


def answer_question(
    question: str,
    *,
    user_id: str = "anonymous",
    role: str | None = None,
    client=None,
    log: bool = True,
) -> Answer:
    """질문 하나를 끝까지 처리한다."""
    blocked = guard(question)
    if blocked:
        return Answer(question=question, answer=blocked, blocked=True)

    try:
        contexts = retrieve(question, role=role, client=client)
    except Exception as exc:  # 검색 계층 장애를 화면까지 그대로 흘리지 않는다
        logger.exception("검색 실패")
        return Answer(question=question, answer="검색 중 오류가 발생했습니다.", error=str(exc))

    try:
        text = ask_llm(question, contexts)
    except LLMError as exc:
        logger.error("생성 실패: %s", exc)
        return Answer(question=question, answer="답변 생성 중 오류가 발생했습니다.",
                      contexts=contexts, error=str(exc))

    confidence, rerank_score, ratio = score_answer(text, contexts)
    result = Answer(
        question=question,
        answer=text,
        contexts=contexts,
        confidence=confidence,
        rerank_score=rerank_score,
        citation_ratio=ratio,
    )

    if log:
        log_qa_event(
            user_id=user_id,
            question=question,
            answer=text,
            sources=result.sources,
            confidence=confidence,
            message_id=result.message_id,
        )
    return result


def main() -> None:
    """python -m pipeline.query "연차는 며칠인가요?" — UI 없이 파이프라인만 확인."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="질문 하나를 파이프라인에 태운다")
    parser.add_argument("question")
    parser.add_argument("--role", default=None, help="RBAC 역할 (예: 인사팀)")
    args = parser.parse_args()

    result = answer_question(args.question, role=args.role, log=False)
    print(f"\n[신뢰도 {result.confidence}] (rerank={result.rerank_score:.3f}, 인용={result.citation_ratio:.2f})")
    print(result.answer)
    print("\n근거 조항:")
    for c in result.contexts:
        print(f"  - {c.get('doc_title')} {c.get('article_no')} (시행 {c.get('effective_date')})")


if __name__ == "__main__":
    main()
