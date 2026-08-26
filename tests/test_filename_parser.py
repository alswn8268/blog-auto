"""파일명 메타데이터 추출 (2.1).

실제 파일명 표기 규칙을 받으면 FILENAME_PATTERN을 교체하고 이 테스트의
기대값만 바꾸면 된다 — 규칙 변경이 어디까지 파급되는지 여기서 바로 드러난다.
"""

import pytest

from metadata.filename_parser import parse_filename_metadata


@pytest.mark.parametrize(
    "filename,title,date,revision",
    [
        ("인사규정(2024.03.15. 일부개정).hwp", "인사규정", "2024-03-15", "일부개정"),
        ("복무규정_20230101_전부개정.hwpx", "복무규정", "2023-01-01", "전부개정"),
        ("보수규정(2022-07-01 제정).hwp", "보수규정", "2022-07-01", "제정"),
        ("회계규정(2024.01.01).hwp", "회계규정", "2024-01-01", "미상"),
    ],
)
def test_규칙에_맞는_파일명(filename, title, date, revision):
    meta = parse_filename_metadata(filename)
    assert meta["doc_title"] == title
    assert meta["effective_date"] == date
    assert meta["revision_type"] == revision


def test_규칙에_맞지_않으면_문서명만_채운다():
    meta = parse_filename_metadata("무제.hwp")
    assert meta["doc_title"] == "무제"
    assert meta["effective_date"] is None


def test_존재하지_않는_날짜는_버린다():
    # 2월 30일 같은 값이 시행일자로 색인되면 개정이력 정렬이 무너진다
    assert parse_filename_metadata("규정(2024.02.30. 개정).hwp")["effective_date"] is None


def test_법령은_doc_type이_법령으로_잡힌다():
    assert parse_filename_metadata("공공기관의 정보공개에 관한 법률(2024.02.29).pdf")["doc_type"] == "법령"
    assert parse_filename_metadata("인사규정(2024.03.15).hwp")["doc_type"] == "사규"
