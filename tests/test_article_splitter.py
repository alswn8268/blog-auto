"""조항 청킹 (2.2). 표·부칙에서 깨지지 않는지가 핵심 검증 지점."""

from chunking.article_splitter import (
    chunk_document,
    make_chunk_id,
    normalize_article_no,
    split_by_article,
)

SAMPLE = """인사규정

제1장 총칙

제1조(목적) 이 규정은 직원의 인사에 관한 사항을 정함을 목적으로 한다.

제 2 조 (적용범위) 이 규정은 재단 소속 전 직원에게 적용한다.

제2장 임용

제15조의2(전보) ① 임용권자는 필요한 경우 직원을 전보할 수 있다.
② 전보는 매년 1회 실시한다.

부칙

제1조(시행일) 이 규정은 2024년 3월 15일부터 시행한다.
"""

META = {
    "doc_title": "인사규정",
    "effective_date": "2024-03-15",
    "revision_type": "일부개정",
    "doc_type": "사규",
    "source_file": "인사규정(2024.03.15. 일부개정).hwp",
}


def test_조_단위로_분할된다():
    chunks = split_by_article(SAMPLE, doc_title="인사규정")
    assert [c["article_no"] for c in chunks] == ["제1조", "제2조", "제15조의2", "제1조"]


def test_조_번호_표기_흔들림을_흡수한다():
    assert normalize_article_no("제 15 조 의 2") == "제15조의2"


def test_조_제목과_소속_장을_함께_뽑는다():
    chunks = split_by_article(SAMPLE, doc_title="인사규정")
    전보 = next(c for c in chunks if c["article_no"] == "제15조의2")
    assert 전보["article_title"] == "전보"
    assert 전보["parent_section"] == "제2장 임용"
    assert "② 전보는 매년 1회 실시한다." in 전보["text"]


def test_부칙_조항은_따로_표시된다():
    chunks = split_by_article(SAMPLE, doc_title="인사규정")
    assert [c["is_addenda"] for c in chunks] == [False, False, False, True]
    assert chunks[-1]["parent_section"] == "부칙"


def test_부칙_제1조가_본문_제1조를_덮어쓰지_않는다():
    ids = [c["id"] for c in chunk_document(SAMPLE, META)]
    assert len(ids) == len(set(ids))


def test_같은_문서를_다시_청킹하면_같은_id가_나온다():
    assert [c["id"] for c in chunk_document(SAMPLE, META)] == [
        c["id"] for c in chunk_document(SAMPLE, META)
    ]


def test_시행일자가_다르면_다른_id가_되어_이력이_남는다():
    old = make_chunk_id("인사규정", "제15조", "2022-01-01")
    new = make_chunk_id("인사규정", "제15조", "2024-03-15")
    assert old != new


def test_조항이_없는_문서는_빈_리스트():
    assert split_by_article("조항이 하나도 없는 안내문입니다.", doc_title="안내") == []


def test_파일명_메타데이터가_모든_청크에_붙는다():
    for c in chunk_document(SAMPLE, META):
        assert c["effective_date"] == "2024-03-15"
        assert c["doc_type"] == "사규"
        assert c["superseded_by"] is None
