"""고도화 1·2단계 — 도메인 라우팅 · Multi-Query · 필터 결합."""

import pytest

from routing.domain_router import CONFIDENCE_THRESHOLD, route, score_domains


# ── 도메인 라우팅 (7장 2단계) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "question,expected",
    [
        ("연차유급휴가 규정은 며칠인가요?", ["사규"]),
        ("출장비 정산 기한과 근무시간 규정은?", ["사규"]),
        ("공공기관 정보공개 법률상 시행령 조문은?", ["법령"]),
        ("대법원 판례에서 판결한 소송 기준은?", ["판례"]),
    ],
)
def test_성격이_뚜렷한_질문은_문서종류를_좁힌다(question, expected):
    assert route(question) == expected


def test_두_영역에_걸친_질문은_좁히지_않는다():
    # "사규가 법률에 어긋나나요?"는 둘 다 봐야 답할 수 있다.
    # 한쪽으로 좁히면 정답 문서가 통째로 검색에서 빠진다.
    assert route("이 사규가 법률에 어긋나지 않나요?") is None


def test_단서가_없으면_좁히지_않는다():
    assert route("그건 어떻게 되나요?") is None
    assert route("") is None


def test_단서_하나로는_좁히지_않는다():
    # 잘못 좁히면 화면에는 "확인되지 않습니다"만 남아 원인을 알 수 없다.
    # 그래서 임계값 미만이면 전체 검색으로 둔다.
    scores = score_domains("규정 알려줘")
    assert max(scores.values()) < CONFIDENCE_THRESHOLD
    assert route("규정 알려줘") is None


def test_라우팅_문서종류는_메타데이터가_만드는_값과_같다():
    from metadata.filename_parser import DOC_TYPE_RULES, guess_doc_type
    from routing.domain_router import DOMAIN_HINTS

    produced = {guess_doc_type("아무규정")} | {doc_type for _, doc_type in DOC_TYPE_RULES}
    # 라우팅이 아는 문서종류가 메타데이터가 만들지 않는 값이면 검색이 조용히 0건이 된다
    assert set(DOMAIN_HINTS) <= produced


# ── Multi-Query (7장 1단계) ────────────────────────────────────────────────


def test_LLM_응답의_번호와_불릿을_걷어낸다(monkeypatch):
    import llm.generate as llm_module
    from pipeline.multi_query import expand_query

    monkeypatch.setattr(
        llm_module, "complete",
        lambda *a, **k: '1. 연차유급휴가 일수\n2) 연차휴가 부여 기준\n- 유급휴가 산정\n',
    )
    assert expand_query("연차 며칠 씀?", n=3) == [
        "연차유급휴가 일수", "연차휴가 부여 기준", "유급휴가 산정",
    ]


def test_꺼져_있으면_LLM을_부르지_않는다(monkeypatch):
    import llm.generate as llm_module
    from pipeline.multi_query import expand_query

    def _boom(*a, **k):
        raise AssertionError("MULTI_QUERY_N=0인데 LLM이 호출됐습니다")

    monkeypatch.setattr(llm_module, "complete", _boom)
    assert expand_query("연차는?", n=0) == []


def test_확장에_실패해도_검색을_막지_않는다(monkeypatch):
    import llm.generate as llm_module
    from pipeline.multi_query import expand_query

    def _boom(*a, **k):
        raise llm_module.LLMError("Ollama 연결 실패")

    monkeypatch.setattr(llm_module, "complete", _boom)
    assert expand_query("연차는?", n=3) == []  # 원 질문만으로 검색은 계속된다


def test_원_질문과_같은_변형은_버린다(monkeypatch):
    import llm.generate as llm_module
    from pipeline.multi_query import expand_query

    monkeypatch.setattr(llm_module, "complete", lambda *a, **k: "연차는?\n연차유급휴가 일수\n연차유급휴가 일수")
    assert expand_query("연차는?", n=3) == ["연차유급휴가 일수"]


# ── 필터 결합 ──────────────────────────────────────────────────────────────


def test_RBAC_필터와_라우팅_필터가_함께_걸린다():
    from qdrant_client import models

    from routing.domain_router import build_routing_filter
    from security.rbac import build_permission_filter
    from vectordb.store import combine_filters

    combined = combine_filters(
        build_permission_filter("전체직원"),          # must_not: 제한 문서
        build_routing_filter("연차유급휴가 규정은?"),  # must: doc_type 사규
    )
    assert isinstance(combined, models.Filter)
    assert combined.must and combined.must_not  # 둘 다 살아 있어야 한다


def test_한쪽이_없으면_다른_쪽을_그대로_쓴다():
    from routing.domain_router import build_routing_filter
    from vectordb.store import combine_filters

    only_routing = build_routing_filter("연차유급휴가 규정은?")
    assert combine_filters(None, only_routing) is only_routing
    assert combine_filters(None, None) is None


def test_should절을_가진_필터는_OR가_섞이지_않게_중첩된다():
    from qdrant_client import models

    from vectordb.store import combine_filters

    a = models.Filter(should=[models.FieldCondition(key="x", match=models.MatchValue(value="1"))])
    b = models.Filter(should=[models.FieldCondition(key="y", match=models.MatchValue(value="2"))])
    combined = combine_filters(a, b)

    # 평평하게 합치면 "x=1 또는 y=2"가 되어 두 조건 다 통과할 필요가 없어진다
    assert len(combined.must) == 2
    assert all(isinstance(m, models.Filter) and m.should for m in combined.must)
