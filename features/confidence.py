"""신뢰도 점수 (명세 4.3).

리랭커 점수(검색이 제대로 됐는가)와 충실도(답변이 근거에 붙어 있는가)를
반씩 섞어 상/중/하 배지로 보여준다.

faithfulness를 매 질문마다 RAGAS로 계산하면 느리기 때문에, 실시간에는
'답변이 실제로 근거 조항을 인용했는가'를 대리 지표로 쓴다.
정식 faithfulness는 3장의 배치 평가에서 계산한다.
"""

from __future__ import annotations

import re

from chunking.article_splitter import normalize_article_no
from llm.generate import NO_CONTEXT_ANSWER

HIGH, MEDIUM, LOW = "상", "중", "하"

ARTICLE_MENTION = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?")


def compute_confidence(rerank_score: float, faithfulness_score: float) -> str:
    combined = 0.5 * rerank_score + 0.5 * faithfulness_score
    if combined >= 0.8:
        return HIGH
    if combined >= 0.5:
        return MEDIUM
    return LOW


def citation_ratio(answer: str, contexts: list[dict]) -> float:
    """답변이 언급한 조항 중 실제 근거 조항에 있는 비율 (실시간 충실도 대리 지표).

    - 조항을 하나도 인용하지 않았으면 0.0 (인용을 강제한 프롬프트를 어긴 것)
    - "확인되지 않습니다"로 답한 경우는 정직한 답이므로 1.0
    """
    if not answer:
        return 0.0
    if "확인되지 않습니다" in answer or answer.strip() == NO_CONTEXT_ANSWER:
        return 1.0

    mentioned = {normalize_article_no(m) for m in ARTICLE_MENTION.findall(answer)}
    if not mentioned:
        return 0.0

    available = {normalize_article_no(c.get("article_no", "")) for c in contexts}
    hit = len(mentioned & available)
    return hit / len(mentioned)


def score_answer(answer: str, contexts: list[dict]) -> tuple[str, float, float]:
    """(배지, rerank_score, 인용충실도)를 한 번에 계산한다."""
    top_score = max((c.get("rerank_score", 0.0) or 0.0) for c in contexts) if contexts else 0.0
    ratio = citation_ratio(answer, contexts)
    return compute_confidence(top_score, ratio), top_score, ratio
