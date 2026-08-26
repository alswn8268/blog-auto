"""도메인 라우팅 (명세 7장 2단계).

질문 성격을 보고 검색 대상 문서종류(doc_type)를 좁힌다.
사규 질문에 법령·판례까지 섞여 들어오면 리랭커가 엉뚱한 조항을 위로 올리는 일이
생기는데, 라우팅은 그 잡음을 검색 단계에서 줄인다.

**설계 원칙: 확신이 없으면 좁히지 않는다.**
라우팅이 틀리면 정답 문서가 통째로 검색에서 빠지고, 화면에는 "확인되지 않습니다"만
남아 사용자는 왜 못 찾았는지 알 수 없다. 좁혀서 얻는 이득보다 잘못 좁혀서 잃는 손해가
크므로, 근거 점수가 임계값을 넘을 때만 필터를 건다(그 외에는 None = 전체 검색).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# doc_type별 단서 표현. 문서종류는 metadata/filename_parser.py의 값과 같아야 한다.
DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "법령": (
        "법률", "법령", "시행령", "시행규칙", "조문", "국가재정법", "공공기관",
        "법적", "법에", "법상", "위법", "법률상",
    ),
    "판례": ("판례", "판결", "대법원", "선고", "소송", "재판"),
    "사규": (
        "사규", "규정", "내규", "복무", "인사", "연차", "휴가", "출장", "근무",
        "보수", "급여", "수당", "징계", "채용", "승진", "전보", "결재",
    ),
}

# 이 점수 아래면 좁히지 않는다. (단서 1개로 문서 범위를 자르지 않기 위한 하한)
CONFIDENCE_THRESHOLD = 2

# 단서가 여러 종류에 걸치면 좁히지 않는다 — "사규가 법에 어긋나나요?" 같은 질문 보호
_WORD = re.compile(r"[가-힣A-Za-z0-9]+")


def score_domains(question: str) -> dict[str, int]:
    """문서종류별 단서 점수. 단순 포함 횟수를 센다."""
    text = question or ""
    return {
        domain: sum(text.count(hint) for hint in hints)
        for domain, hints in DOMAIN_HINTS.items()
    }


def route(question: str) -> list[str] | None:
    """검색을 좁힐 문서종류 목록. 확신이 없으면 None(=전체 검색).

    - 최고 점수가 임계값 미만 → None
    - 1·2위가 동점이거나 근소한 차이 → None (질문이 두 영역에 걸쳐 있다는 뜻)
    """
    scores = score_domains(question)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_domain, top_score), (_, second_score) = ranked[0], ranked[1]

    if top_score < CONFIDENCE_THRESHOLD:
        return None
    if top_score - second_score < CONFIDENCE_THRESHOLD:
        return None

    logger.debug("라우팅: %s (점수 %s)", top_domain, scores)
    return [top_domain]


def build_routing_filter(question: str):
    """라우팅 결과를 Qdrant 필터로. 좁히지 않기로 했으면 None."""
    from qdrant_client import models

    domains = route(question)
    if not domains:
        return None
    return models.Filter(
        must=[models.FieldCondition(key="doc_type", match=models.MatchAny(any=domains))]
    )
