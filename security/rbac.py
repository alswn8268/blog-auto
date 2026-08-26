"""RBAC — 역할 기반 접근 제어 (명세 6.2 — 애플리케이션 계층).

모델: **기본은 공개, 예외만 제한**한다.
사규·법령 대부분은 전 직원이 봐야 하는 문서이므로, 열람 제한이 필요한 소수 문서만
RESTRICTED_DOCS에 올리고 그 문서를 볼 수 있는 부서를 ROLE_EXTRA_DOCS에 적는다.
(허용 목록 방식으로 짜면 새 사규를 색인할 때마다 목록에 추가해야 하고, 빠뜨리면
아무도 못 보게 된다 — 조용히 검색이 0건이 되므로 알아차리기도 어렵다.)

Qdrant는 검색 시점에 payload 필터를 걸 수 있어 별도 접근제어 서버 없이 구현된다.

주의: 필터는 검색 단계에서 걸어야 의미가 있다. 검색해온 뒤 화면에서 걸러내는 방식은
LLM 프롬프트에 이미 원문이 들어간 뒤라 접근제어가 아니다.
"""

from __future__ import annotations

# 열람 제한 문서(문서명 기준). 여기 없는 문서는 전 직원이 볼 수 있다.
RESTRICTED_DOCS: frozenset[str] = frozenset(
    {"인사규정", "보수규정", "회계규정", "감사규정", "임원보수규정"}
)

# 부서별로 추가 열람이 허용되는 제한 문서
ROLE_EXTRA_DOCS: dict[str, frozenset[str]] = {
    "인사팀": frozenset({"인사규정", "보수규정", "임원보수규정"}),
    "재무팀": frozenset({"회계규정", "보수규정"}),
    "감사실": frozenset(RESTRICTED_DOCS),  # 감사 목적상 전체 열람
}

DEFAULT_ROLE = "전체직원"
DEPT_HEADER = "X-User-Dept"


def get_user_role(request) -> str:
    """사내 SSO가 발급한 세션/JWT에서 부서 클레임을 읽는다.

    프로토타입 단계에서는 리버스 프록시가 넣어주는 헤더를 그대로 읽는다.
    (헤더는 위조 가능하므로, 운영 전환 시 SSO 서명 검증으로 반드시 교체할 것.)
    """
    headers = getattr(request, "headers", {}) or {}
    return headers.get(DEPT_HEADER, DEFAULT_ROLE)


def denied_docs(role: str) -> list[str]:
    """이 역할에게 가려지는 문서명 목록."""
    return sorted(RESTRICTED_DOCS - ROLE_EXTRA_DOCS.get(role, frozenset()))


def build_permission_filter(role: str):
    """역할이 볼 수 없는 문서를 검색 대상에서 제외하는 Qdrant 필터.

    가릴 문서가 없으면 None을 돌려준다 — 불필요한 필터를 붙이지 않는다.
    """
    from qdrant_client import models

    denied = denied_docs(role)
    if not denied:
        return None
    return models.Filter(
        must_not=[models.FieldCondition(key="doc_title", match=models.MatchAny(any=denied))]
    )


def can_access(role: str, chunk: dict) -> bool:
    """검색 결과 하나가 이 역할에게 노출 가능한지 (테스트·이중 확인용)."""
    return chunk.get("doc_title") not in denied_docs(role)
