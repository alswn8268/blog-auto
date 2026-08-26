"""조항 구조 인식 청킹 (명세 2.2).

법령·사규 특유의 `제n조`, `제n장` 구조를 정규식으로 인식해 조 단위를 1차 청크로 삼는다.
표·부칙·별지서식은 정규식만으로는 깨질 수 있으므로, 1주차에 실제 샘플 문서로 반드시 검증할 것.
"""

from __future__ import annotations

import hashlib
import re

# "제15조", "제15조의2", "제 15 조(목적)" 모두 인식
ARTICLE_PATTERN = re.compile(r"(제\s*\d+\s*조(?:의\s*\d+)?)\s*(\([^)\n]{0,80}\))?")

# 장/절/관 — 조항이 어느 장에 속하는지(parent_section) 추적하는 데 쓴다
SECTION_PATTERN = re.compile(r"^\s*(제\s*\d+\s*[장절관])\s*(.*)$", re.MULTILINE)

# 부칙 이후는 본문 조항과 성격이 달라 따로 표시한다
ADDENDA_PATTERN = re.compile(r"^\s*부\s*칙", re.MULTILINE)

# 조 번호 표기 흔들림("제 15 조" vs "제15조")을 흡수하기 위한 정규화
_SPACES = re.compile(r"\s+")


def normalize_article_no(article_no: str) -> str:
    """'제 15 조 의 2' → '제15조의2'. 개정 전후 조항 매칭 키로 쓴다."""
    return _SPACES.sub("", article_no)


def _section_index(text: str) -> list[tuple[int, str]]:
    """(위치, 장/절 제목) 목록. 조항 위치로 소속 장을 되짚는 데 쓴다."""
    index = []
    for m in SECTION_PATTERN.finditer(text):
        title = _SPACES.sub(" ", f"{m.group(1)} {m.group(2)}").strip()
        index.append((m.start(), title))
    return index


def _section_at(index: list[tuple[int, str]], pos: int) -> str:
    current = ""
    for start, title in index:
        if start <= pos:
            current = title
        else:
            break
    return current


def make_chunk_id(
    doc_title: str,
    article_no: str,
    effective_date: str | None,
    *,
    is_addenda: bool = False,
) -> str:
    """문서·조항·시행일자로 결정되는 안정적인 ID.

    같은 문서를 다시 색인해도 같은 ID가 나오므로 upsert가 중복을 만들지 않고,
    시행일자가 다르면 다른 ID가 되므로 개정 이력이 함께 남는다.
    부칙에도 '제1조'가 다시 나오므로 본문 조항과 ID가 겹치지 않도록 구분한다.
    """
    scope = "부칙" if is_addenda else "본문"
    raw = f"{doc_title}|{scope}|{normalize_article_no(article_no)}|{effective_date or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def split_by_article(
    text: str,
    doc_title: str,
    parent_section: str = "",
    *,
    min_chars: int = 10,
) -> list[dict]:
    """조 단위로 분할하고 각 조각에 메타데이터를 붙인다.

    parent_section을 명시하면 그 값을 모든 청크에 그대로 쓰고,
    비워두면 본문에서 찾은 장/절 제목을 조항별로 자동으로 채운다.
    첫 조항 앞의 머리말(제명·목차)은 청크로 만들지 않는다.
    """
    matches = list(ARTICLE_PATTERN.finditer(text))
    if not matches:
        return []

    sections = _section_index(text) if not parent_section else []
    addenda = ADDENDA_PATTERN.search(text)
    addenda_at = addenda.start() if addenda else None

    chunks: list[dict] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < min_chars:
            continue

        is_addenda = addenda_at is not None and start >= addenda_at
        section = "부칙" if is_addenda else (parent_section or _section_at(sections, start))

        chunks.append(
            {
                "article_no": normalize_article_no(m.group(1)),
                "article_title": (m.group(2) or "").strip("()").strip(),
                "text": body,
                "doc_title": doc_title,
                "parent_section": section,
                "is_addenda": is_addenda,
            }
        )
    return chunks


def chunk_document(text: str, meta: dict) -> list[dict]:
    """파일명 메타데이터(2.1)를 조항 청크에 합쳐 색인 직전 형태로 만든다."""
    doc_title = meta.get("doc_title") or "미상"
    chunks = split_by_article(text, doc_title=doc_title)
    for c in chunks:
        c.update(
            {
                "doc_type": meta.get("doc_type", "사규"),
                "effective_date": meta.get("effective_date"),
                "revision_type": meta.get("revision_type"),
                "source_file": meta.get("source_file", ""),
                "superseded_by": None,
                "id": make_chunk_id(
                    doc_title,
                    c["article_no"],
                    meta.get("effective_date"),
                    is_addenda=c["is_addenda"],
                ),
            }
        )
    return chunks


def format_context(chunk: dict) -> str:
    """LLM 프롬프트·화면에 넣을 인용 표기."""
    title = f" ({chunk['article_title']})" if chunk.get("article_title") else ""
    return f"[{chunk.get('doc_title', '')} {chunk.get('article_no', '')}{title}]"
