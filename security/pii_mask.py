"""개인정보 마스킹 (명세 6.2 — 데이터 계층).

질문에 개인정보가 섞여 들어오는 경우(예: "OOO 직원 연봉이…")를 1차로 정규식 필터링한다.

한계: 정규식은 형식이 정해진 정보(주민번호·전화번호·계좌)에는 효과적이지만,
이름·직급처럼 문맥으로만 판단되는 정보는 놓친다.
정확도를 더 높이려면 NER(개체명인식) 모델을 2차 필터로 붙이는 것이 고도화 과제다.
"""

from __future__ import annotations

import re

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "주민등록번호": re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"),
    "외국인등록번호": re.compile(r"\b\d{6}[-\s]?[5-8]\d{6}\b"),
    "전화번호": re.compile(r"\b01\d[-\s]?\d{3,4}[-\s]?\d{4}\b"),
    "이메일": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "계좌번호": re.compile(r"\b\d{2,6}-\d{2,6}-\d{2,8}\b"),
    "카드번호": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
}

# 앞에서부터 순서대로 적용한다. 더 구체적인 패턴이 먼저 와야 덜 구체적인 패턴에 먹히지 않는다.
_ORDER = ("주민등록번호", "외국인등록번호", "카드번호", "전화번호", "이메일", "계좌번호")


def mask_pii(text: str) -> str:
    """탐지된 개인정보를 "[유형 마스킹됨]"으로 바꾼다."""
    if not text:
        return text
    for name in _ORDER:
        text = PII_PATTERNS[name].sub(f"[{name} 마스킹됨]", text)
    return text


def detect_pii(text: str) -> list[str]:
    """어떤 유형이 탐지됐는지만 돌려준다. 관리자 화면 통계용.

    마스킹과 같은 순서로 훑으면서 이미 가려진 부분은 다시 세지 않는다.
    (전화번호가 계좌번호 패턴에도 걸리는 식의 중복 집계 방지)
    """
    found = []
    text = text or ""
    for name in _ORDER:
        pattern = PII_PATTERNS[name]
        if pattern.search(text):
            found.append(name)
            text = pattern.sub("", text)
    return found
