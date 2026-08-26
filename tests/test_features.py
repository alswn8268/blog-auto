"""차별화 기능 (4장) — 신뢰도·개정 diff·충돌 후보·재색인 대상 선별."""

import pytest

from features.auto_reindex import diff_chunks, file_hash
from features.conflict_detect import cosine_sim, find_conflict_candidates
from features.confidence import citation_ratio, compute_confidence, score_answer
from features.revision_diff import build_revision_history, diff_articles, is_changed, similarity

CONTEXTS = [
    {"article_no": "제20조", "doc_title": "복무규정", "text": "연차는 15일로 한다.", "rerank_score": 0.9},
    {"article_no": "제21조", "doc_title": "복무규정", "text": "연차는 이월할 수 없다.", "rerank_score": 0.4},
]


# ── 4.3 신뢰도 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rerank,faith,expected",
    [(0.9, 0.9, "상"), (0.8, 0.4, "중"), (0.3, 0.2, "하"), (0.8, 0.8, "상")],
)
def test_신뢰도_등급(rerank, faith, expected):
    assert compute_confidence(rerank, faith) == expected


def test_근거가_약하면_인용이_완벽해도_하로_내려간다():
    # 검색이 관련 없는 조항을 물어왔는데 인용 형식만 맞는 경우.
    # 가중 평균만 쓰면 0.5가 되어 '중'으로 보이지만, 사용자에게는 근거 없는 답이다.
    assert compute_confidence(0.0, 1.0) == "하"
    assert compute_confidence(0.29, 1.0) == "하"
    assert compute_confidence(0.31, 1.0) == "중"


def test_근거에_있는_조항만_인용하면_충실도가_1이다():
    assert citation_ratio("연차는 15일입니다.\n근거: 복무규정 제20조", CONTEXTS) == 1.0


def test_없는_조항을_지어내면_충실도가_떨어진다():
    assert citation_ratio("근거: 제20조, 제99조", CONTEXTS) == 0.5


def test_조항을_아예_인용하지_않으면_0이다():
    # 인용을 강제한 프롬프트를 어긴 답변이므로 신뢰도가 낮게 나와야 한다
    assert citation_ratio("연차는 15일입니다.", CONTEXTS) == 0.0


def test_모른다고_답한_경우는_정직한_답으로_본다():
    assert citation_ratio("확인되지 않습니다.", CONTEXTS) == 1.0


def test_지어낸_답변은_배지가_하로_내려간다():
    badge, _, _ = score_answer("연차는 30일입니다.", CONTEXTS)
    assert badge == "하"


# ── 4.2 개정 이력 ──────────────────────────────────────────────────────────


def test_공백_차이만으로는_개정으로_보지_않는다():
    assert not is_changed("연차는  15일로\n한다.", "연차는 15일로 한다.")


def test_내용이_바뀌면_개정으로_본다():
    assert is_changed("연차는 15일로 한다.", "연차는 20일로 한다.")


def test_diff에_개정_전후가_표시된다():
    d = diff_articles("연차는 15일로 한다.", "연차는 20일로 한다.")
    assert "-연차는 15일로 한다." in d
    assert "+연차는 20일로 한다." in d


def test_변경이_없으면_빈_diff():
    assert diff_articles("같은 내용", "같은 내용") == ""
    assert similarity("같은 내용", "같은 내용") == 1.0


def test_개정_이력은_시행일자_순으로_정렬된다():
    history = build_revision_history(
        [
            {"effective_date": "2024-03-15", "text": "20일", "revision_type": "일부개정"},
            {"effective_date": "2022-01-01", "text": "15일", "revision_type": "제정"},
        ]
    )
    assert len(history) == 1
    assert history[0]["from_date"] == "2022-01-01"
    assert history[0]["to_date"] == "2024-03-15"


# ── 4.1 충돌 탐지 ──────────────────────────────────────────────────────────


def test_코사인_유사도():
    assert cosine_sim([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine_sim([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)
    assert cosine_sim([0, 0, 0], [1, 0, 0]) == 0.0  # 0벡터에서 나눗셈 오류가 나지 않아야 한다


def test_비슷하지만_같지는_않은_쌍만_후보가_된다():
    articles = [
        {"id": "a", "doc_title": "인사규정", "embedding": [1.0, 0.0, 0.0]},
        {"id": "b", "doc_title": "복무규정", "embedding": [0.8, 0.6, 0.0]},  # sim 0.8 → 후보
        {"id": "c", "doc_title": "인사규정", "embedding": [1.0, 0.0, 0.0]},  # sim 1.0 → 동일, 제외
        {"id": "d", "doc_title": "인사규정", "embedding": [0.0, 1.0, 0.0]},  # sim 0.0 → 무관, 제외
    ]
    pairs = {frozenset((a, b)) for a, b, _ in find_conflict_candidates(articles, 0.70, 0.85)}
    assert pairs == {frozenset(("a", "b")), frozenset(("b", "c"))}


def test_임베딩이_없는_조항은_건너뛴다():
    articles = [{"id": "a", "embedding": [1.0, 0.0]}, {"id": "b"}]
    assert find_conflict_candidates(articles) == []


# ── 4.4 자동 재색인 ────────────────────────────────────────────────────────


def test_실제로_바뀐_조항만_재색인_대상이_된다():
    old = [
        {"article_no": "제1조", "text": "목적", "id": "1"},
        {"article_no": "제 2 조", "text": "적용범위", "id": "2"},
    ]
    new = [
        {"article_no": "제1조", "text": "목적"},           # 그대로 → 제외
        {"article_no": "제2조", "text": "적용범위 개정"},   # 개정 → 포함
        {"article_no": "제3조", "text": "신설 조항"},       # 신설 → 포함
    ]
    changed = diff_chunks(old, new)
    assert [n["article_no"] for _, n in changed] == ["제2조", "제3조"]
    assert changed[0][0]["id"] == "2"   # 표기가 흔들려도 기존 조항과 매칭된다
    assert changed[1][0] is None        # 신설 조항은 대응하는 기존본이 없다


def test_부칙_제1조가_본문_제1조와_비교되지_않는다():
    # 부칙에도 '제1조'가 나온다. 구분하지 않으면 바뀌지도 않은 본문 제1조가
    # 부칙 제1조와 비교돼 매번 개정으로 잡히고, 불필요한 재임베딩이 발생한다.
    old = [
        {"article_no": "제1조", "text": "목적", "is_addenda": False, "id": "1"},
        {"article_no": "제1조", "text": "시행일", "is_addenda": True, "id": "2"},
    ]
    new = [
        {"article_no": "제1조", "text": "목적", "is_addenda": False},
        {"article_no": "제1조", "text": "시행일", "is_addenda": True},
    ]
    assert diff_chunks(old, new) == []


def test_파일_해시는_내용이_같으면_같다(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"same"), b.write_bytes(b"same"), c.write_bytes(b"different")
    assert file_hash(a) == file_hash(b) != file_hash(c)
