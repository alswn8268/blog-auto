"""개정 이력 diff (명세 4.2).

같은 조항의 개정 전/후 본문을 줄 단위로 비교해 보여준다.
4.4의 자동 재색인이 "실제로 내용이 바뀐 조항"을 골라낼 때도 이 모듈을 재사용한다.
"""

from __future__ import annotations

import difflib
import re

_WS = re.compile(r"\s+")


def normalize_for_compare(text: str) -> str:
    """줄바꿈·공백 차이만으로 '개정됨'으로 잡히는 것을 막는다."""
    return _WS.sub(" ", text or "").strip()


def is_changed(old_text: str, new_text: str) -> bool:
    return normalize_for_compare(old_text) != normalize_for_compare(new_text)


def diff_articles(old_text: str, new_text: str) -> str:
    """unified diff 문자열. 변경이 없으면 빈 문자열."""
    diff = difflib.unified_diff(
        (old_text or "").splitlines(),
        (new_text or "").splitlines(),
        lineterm="",
        fromfile="개정 전",
        tofile="개정 후",
    )
    return "\n".join(diff)


def similarity(old_text: str, new_text: str) -> float:
    """0~1. 개정 폭이 얼마나 큰지 가늠하는 보조 지표."""
    return difflib.SequenceMatcher(
        None, normalize_for_compare(old_text), normalize_for_compare(new_text)
    ).ratio()


def diff_html(old_text: str, new_text: str) -> str:
    """Streamlit 화면에 그대로 넣을 수 있는 마크다운 코드블록."""
    body = diff_articles(old_text, new_text)
    if not body:
        return "_변경 없음_"
    return f"```diff\n{body}\n```"


def build_revision_history(versions: list[dict]) -> list[dict]:
    """같은 조항의 여러 버전을 시행일자 순으로 늘어놓고 인접 버전 간 diff를 만든다.

    versions: [{"effective_date": ..., "text": ..., "revision_type": ...}, ...]
    """
    ordered = sorted(versions, key=lambda v: v.get("effective_date") or "")
    history = []
    for prev, cur in zip(ordered, ordered[1:]):
        history.append(
            {
                "from_date": prev.get("effective_date"),
                "to_date": cur.get("effective_date"),
                "revision_type": cur.get("revision_type"),
                "similarity": similarity(prev.get("text", ""), cur.get("text", "")),
                "diff": diff_articles(prev.get("text", ""), cur.get("text", "")),
            }
        )
    return history
