"""RBAC — 역할 기반 접근 제어 (명세 6.2 — 애플리케이션 계층).

부서별로 열람 가능한 문서 범위를 다르게 한다.
Qdrant는 검색 시점에 payload 필터를 걸 수 있어 별도 접근제어 서버 없이 구현된다.

주의: 필터는 검색 단계에서 걸어야 의미가 있다. 검색해온 뒤 화면에서 걸러내는 방식은
LLM 프롬프트에 이미 원문이 들어간 뒤라 접근제어가 아니다.
"""

from __future__ import annotations

# 부서(역할) → 열람 허용 문서명·문서종류 목록
ROLE_DOC_MAP: dict[str, list[str]] = {
    "인사팀": ["인사규정", "복무규정", "보수규정", "일반사규", "법령"],
    "감사실": ["인사규정", "복무규정", "보수규정", "회계규정", "일반사규", "법령"],
    "전체직원": ["일반사규", "법령"],
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


def allowed_docs(role: str) -> list[str]:
    return ROLE_DOC_MAP.get(role, ROLE_DOC_MAP[DEFAULT_ROLE])


def build_permission_filter(role: str):
    """역할이 볼 수 있는 문서로만 검색 범위를 좁히는 Qdrant 필터.

    doc_title(문서명) 또는 doc_type(문서종류) 중 하나라도 허용 목록에 있으면 통과시킨다.
    (Qdrant는 should 절 중 최소 하나가 만족돼야 통과시킨다.)
    """
    from qdrant_client import models

    allowed = allowed_docs(role)
    return models.Filter(
        should=[
            models.FieldCondition(key="doc_title", match=models.MatchAny(any=allowed)),
            models.FieldCondition(key="doc_type", match=models.MatchAny(any=allowed)),
        ]
    )


def can_access(role: str, chunk: dict) -> bool:
    """검색 결과 하나가 이 역할에게 노출 가능한지 (테스트·이중 확인용)."""
    allowed = set(allowed_docs(role))
    return chunk.get("doc_title") in allowed or chunk.get("doc_type") in allowed
