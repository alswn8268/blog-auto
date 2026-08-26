"""Multi-Query 확장 (명세 7장 1단계).

사용자 질문 하나를 여러 표현으로 바꿔 각각 검색한 뒤 결과를 함께 융합한다.
사규 질문은 구어체("연차 며칠 씀?")로 들어오는데 원문은 문어체("연차유급휴가")라
표현이 어긋나면 검색이 실패한다. 질문 쪽을 여러 각도로 펼쳐 그 간극을 메운다.

비용: LLM 호출이 질문당 한 번 더 붙고 검색 갈래가 늘어 지연시간이 증가한다.
그래서 기본값은 꺼짐(MULTI_QUERY_N=0)이며, RAGAS로 효과를 확인한 뒤 켜는 것을 권한다.
"""

from __future__ import annotations

import logging
import re

from config import get_settings

logger = logging.getLogger(__name__)

EXPANSION_PROMPT = """다음 질문을 사규·법령 원문에서 찾기 좋은 표현으로 {n}개 바꿔 쓰세요.

규칙:
- 의미를 바꾸지 마세요. 묻는 대상이 달라지면 안 됩니다.
- 구어체는 규정 원문에 쓰이는 문어체로 바꾸세요. (예: "연차 며칠 씀?" → "연차유급휴가 일수")
- 서로 다른 각도로 쓰세요. 같은 말을 반복하지 마세요.
- 설명 없이 한 줄에 하나씩, {n}줄만 출력하세요.

질문: {question}
"""

# LLM이 번호·불릿을 붙여 답하는 경우가 많아 걷어낸다
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _clean(line: str) -> str:
    return _BULLET.sub("", line).strip().strip('"').strip("'")


def expand_query(question: str, n: int | None = None, model: str | None = None) -> list[str]:
    """원 질문을 제외한 변형 질문 목록. 실패하면 빈 리스트(=원 질문만 사용).

    확장에 실패했다고 검색까지 막을 이유는 없으므로 예외를 밖으로 내보내지 않는다.
    """
    s = get_settings()
    n = s.multi_query_n if n is None else n
    if n <= 0 or not question.strip():
        return []

    from llm.generate import LLMError, complete

    try:
        raw = complete(EXPANSION_PROMPT.format(n=n, question=question), model=model, temperature=0.3)
    except LLMError as exc:
        logger.warning("Multi-Query 확장 실패, 원 질문만 사용합니다: %s", exc)
        return []

    variants = []
    for line in raw.splitlines():
        cleaned = _clean(line)
        if cleaned and cleaned != question.strip() and cleaned not in variants:
            variants.append(cleaned)
    return variants[:n]


def embed_variants(variants: list[str]) -> list[tuple[list[float], dict[str, float]]]:
    """변형 질문을 (dense, sparse) 쌍으로 인코딩한다 — hybrid_search의 extra_queries 형태."""
    if not variants:
        return []
    from embedding.embedder import get_embedder

    result = get_embedder().encode(variants)
    return list(zip(result.dense, result.sparse))
