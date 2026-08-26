"""파일명 기반 메타데이터 추출 (명세 2.1).

본문을 파싱하지 않고도 파일명만으로 시행일자를 뽑아낸다.
여기서 뽑은 effective_date는 '문서 처리일'이 아니라 '실제 시행일자'이므로,
4.4의 자동 재색인과 4.2의 개정이력 추적이 실제 규정 이력과 그대로 맞아떨어진다.

아래 정규식은 "문서명(YYYY.MM.DD. 개정구분).hwp" 형태를 가정한 예시다.
실제 파일명 표기 규칙을 확인한 뒤 FILENAME_PATTERN만 그 형식에 맞게 교체하면 된다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# 예: "인사규정(2024.03.15. 일부개정).hwp", "인사규정_20240315_일부개정.hwp"
FILENAME_PATTERN = re.compile(
    r"(?P<doc_title>[^()_]+)"
    r"[(_]\s*(?P<year>\d{4})[.\-]?(?P<month>\d{2})[.\-]?(?P<day>\d{2})\.?\s*"
    r"[._\s]*(?P<revision_type>제정|전부개정|일부개정|폐지|개정)?"
)

REVISION_UNKNOWN = "미상"

# doc_title로 문서 종류를 추정하는 규칙. RBAC 필터·도메인 라우팅에 쓰인다.
DOC_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("법", "법령"),
    ("법률", "법령"),
    ("시행령", "법령"),
    ("시행규칙", "법령"),
    ("판례", "판례"),
)


def guess_doc_type(doc_title: str) -> str:
    """문서명에서 doc_type을 추정한다. 규칙에 걸리지 않으면 사규로 본다."""
    for keyword, doc_type in DOC_TYPE_RULES:
        if doc_title.endswith(keyword):
            return doc_type
    return "사규"


def _valid_date(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_filename_metadata(filename: str) -> dict:
    """파일명에서 문서명·시행일자·개정구분을 뽑는다.

    규칙에 맞지 않는 파일명이면 시행일자 없이 문서명만 채워 돌려준다.
    (색인 자체를 막지는 않고, 시행일자는 호출부에서 보정한다.)
    """
    stem = Path(filename).stem
    m = FILENAME_PATTERN.search(stem)
    if not m:
        return {
            "doc_title": stem.strip(),
            "effective_date": None,
            "revision_type": None,
            "doc_type": guess_doc_type(stem.strip()),
        }

    doc_title = m.group("doc_title").strip()
    return {
        "doc_title": doc_title,
        "effective_date": _valid_date(m.group("year"), m.group("month"), m.group("day")),
        "revision_type": m.group("revision_type") or REVISION_UNKNOWN,
        "doc_type": guess_doc_type(doc_title),
    }
