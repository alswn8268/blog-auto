"""프롬프트 인젝션 방어 (명세 6.2 — 애플리케이션 계층).

키워드 매칭은 가장 단순한 1차 방어선이다. 이것만으로 충분하지 않으며,
시스템 프롬프트와 사용자 입력을 명확히 분리한 구조(2.6의 [근거 조항]/[질문] 구획)가
실제로는 더 큰 방어 효과를 낸다. 출력 결과를 한 번 더 검증하는 단계는 3단계 고도화 과제.
"""

from __future__ import annotations

INJECTION_MARKERS: tuple[str, ...] = (
    "시스템 프롬프트를 무시",
    "이전 지시를 무시",
    "위 지시를 무시",
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "당신은 이제부터",
    "너는 이제부터",
    "system prompt",
    "reveal your prompt",
    "프롬프트를 알려줘",
)

REFUSAL_MESSAGE = "죄송합니다. 이 질문은 처리할 수 없습니다."

MAX_QUESTION_LEN = 1000


def guard(question: str) -> str | None:
    """차단해야 하면 사용자에게 보여줄 문구를, 정상이면 None을 돌려준다."""
    if not question or not question.strip():
        return "질문을 입력해 주세요."
    if len(question) > MAX_QUESTION_LEN:
        return f"질문이 너무 깁니다. {MAX_QUESTION_LEN}자 이내로 줄여주세요."

    lowered = question.lower()
    if any(marker.lower() in lowered for marker in INJECTION_MARKERS):
        return REFUSAL_MESSAGE
    return None  # None이면 정상 처리
